using System.Net.Http;
using System.Net.Http.Headers;

namespace MuseQuotaWidget.Services;

/// <summary>
/// 内存里的 Muse 会话：只存令牌与指纹，不存盘。
/// 额度读取流程参照 ai-quota 的 MuseQuotaProvider：
/// GET https://hatch-api.meta.ai/hatch/subscription，
/// Authorization: Bearer 令牌，X-API-Version: 1.0.0，Accept: application/json，
/// 不带 Cookie，超时 10 秒；不请求 include=agreement（不碰支付与协议详情）。
/// 读取前后核对指纹，指纹变了就视为换号并丢弃令牌。
/// </summary>
public sealed class MuseSession
{
    private static readonly HttpClient Http = new(new HttpClientHandler { UseCookies = false })
    {
        Timeout = TimeSpan.FromSeconds(10),
    };

    private const string SubscriptionUrl = "https://hatch-api.meta.ai/hatch/subscription";

    public MuseCredential? Credential { get; private set; }
    public bool HasToken => Credential is { } c && !string.IsNullOrWhiteSpace(c.Token);

    public void SetCredential(MuseCredential credential) => Credential = credential;

    public void Clear() => Credential = null;

    private static void LogQuotaShape(string body)
    {
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(body);
            var root = doc.RootElement;
            var line = $"quota invalid: top=[{MuseDiagnostics.DescribeKeys(root)}]";
            if (root.ValueKind == System.Text.Json.JsonValueKind.Object
                && root.TryGetProperty("usage", out var usage))
            {
                line += $" usage=[{MuseDiagnostics.DescribeKeys(usage)}]";
                if (usage.ValueKind == System.Text.Json.JsonValueKind.Object
                    && usage.TryGetProperty("state", out var state)
                    && state.ValueKind == System.Text.Json.JsonValueKind.String)
                {
                    line += $" state={state.GetString()}";
                }
            }

            MuseDiagnostics.Log(line);
        }
        catch
        {
            MuseDiagnostics.Log("quota invalid: body is not valid JSON");
        }
    }

    /// <summary>
    /// 额外 token 对数专用：把 hatch-api 返回体里的数值字段原样记到
    /// 诊断日志里（不记令牌、账号 id、Cookie），用于确认到底哪个字段
    /// 才是 agent 侧说的 31B。数值本身是用户自己的额度，不是凭据，
    /// 且日志只在本机，用户自己决定要不要发出来。
    /// 注意：这里不做任何换算、不乘系数，看到什么就是什么，
    /// 绝不为了凑 31 亿去硬改一个数。
    /// </summary>
    public static void LogQuotaNumbers(string body)
    {
        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(body);
            var root = doc.RootElement;
            if (root.ValueKind != System.Text.Json.JsonValueKind.Object)
            {
                return;
            }

            var parts = new List<string>();
            void Collect(System.Text.Json.JsonElement obj, string prefix)
            {
                foreach (var prop in obj.EnumerateObject())
                {
                    var name = prop.Name.ToLowerInvariant();
                    // 凭据类字段一律跳过，哪怕它恰好是数字。
                    if (name.Contains("token") || name.Contains("viewer") || name.Contains("session")
                        || name.Contains("auth") || name.Contains("id") && name != "tier_id")
                    {
                        continue;
                    }

                    if (prop.Value.ValueKind == System.Text.Json.JsonValueKind.Number
                        && prop.Value.TryGetDouble(out var num))
                    {
                        parts.Add($"{prefix}{prop.Name}={num}");
                    }
                    else if (prop.Value.ValueKind == System.Text.Json.JsonValueKind.Object
                        && (prefix == string.Empty || prefix == "usage."))
                    {
                        // 只深入一层 usage，避免把整棵树都展开。
                        Collect(prop.Value, prefix + prop.Name + ".");
                    }
                }
            }

            Collect(root, string.Empty);
            if (parts.Count > 0)
            {
                MuseDiagnostics.Log("quota numbers: " + string.Join(", ", parts));
            }
        }
        catch
        {
            // 诊断失败不影响正常流程。
        }
    }

    public async Task<Models.QuotaData> FetchQuotaAsync()
    {
        var credential = Credential;
        if (credential is null || string.IsNullOrWhiteSpace(credential.Token))
        {
            throw new MuseAuthException(MuseAuthKind.LoginRequired);
        }

        using var request = new HttpRequestMessage(HttpMethod.Get, SubscriptionUrl);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credential.Token);
        request.Headers.Add("X-API-Version", "1.0.0");
        request.Headers.Accept.ParseAdd("application/json");

        HttpResponseMessage response;
        try
        {
            response = await Http.SendAsync(request);
        }
        catch (TaskCanceledException)
        {
            throw new MuseAuthException(MuseAuthKind.NetworkUnavailable);
        }
        catch (HttpRequestException)
        {
            throw new MuseAuthException(MuseAuthKind.NetworkUnavailable);
        }

        var body = await response.Content.ReadAsStringAsync();

        // 读取后核对身份：会话在读取期间被换掉（例如点了退出登录），
        // 这次结果就不能算当前账号的，丢弃并按换号处理。
        if (Credential is null || Credential.Fingerprint != credential.Fingerprint)
        {
            Clear();
            throw new MuseAuthException(MuseAuthKind.AccountChanged);
        }

        if ((int)response.StatusCode == 401)
        {
            Clear();
            throw new MuseAuthException(MuseAuthKind.LoginRequired, 401);
        }

        if ((int)response.StatusCode == 429)
        {
            throw new MuseAuthException(MuseAuthKind.RateLimited, 429);
        }

        if (!response.IsSuccessStatusCode)
        {
            throw new MuseAuthException(MuseAuthKind.RequestRejected, (int)response.StatusCode);
        }

        if (string.IsNullOrWhiteSpace(body) || body.Length > 1_048_576)
        {
            throw new MuseAuthException(MuseAuthKind.InvalidResponse);
        }

        try
        {
            var data = MuseApiDecoder.ParseQuota(body);
            // 每次成功也记一行数值字段（只记额度数值，不记凭据），
            // 用于对额外 token 的数；日志会随刷新增长，可随时删除。
            LogQuotaNumbers(body);
            return data;
        }
        catch (MuseAuthException)
        {
            // 只记结构不记值：顶层字段名、usage 字段名、state，
            // 帮助定位是哪个字段对不上，令牌与数值一律不记。
            LogQuotaShape(body);
            throw;
        }
        catch
        {
            LogQuotaShape(body);
            throw new MuseAuthException(MuseAuthKind.InvalidResponse);
        }
    }
}
