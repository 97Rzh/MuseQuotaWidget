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
            return MuseApiDecoder.ParseQuota(body);
        }
        catch (MuseAuthException)
        {
            throw;
        }
        catch
        {
            throw new MuseAuthException(MuseAuthKind.InvalidResponse);
        }
    }
}
