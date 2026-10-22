using System.IO;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace MuseQuotaWidget.Services;

/// <summary>
/// 共用的 WebView 登录换令牌逻辑：可见登录窗和后台登录窗都用它，
/// 保证两路行为一致。WebView2 数据文件夹是同一个，Cookie 共享，
/// 所以后台窗能用可见窗留下的登录 Cookie 静默换令牌。
/// 在 WebView 里同源执行一次 POST /api/auth/check（ai-quota 的做法），
/// 只取 outcome / access_token / viewer_id / session_binding_id /
/// type / reason / status 这几个字段，不取 Cookie，不把令牌发给别处。
/// 返回 null 表示本次未拿到新令牌，调用方按指纹决定是否复用旧令牌。
/// </summary>
public static class MuseWebAuth
{
    public static string UserDataFolder { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "MuseQuotaWidget", "WebView2");

    public static async Task<CoreWebView2Environment> CreateEnvironmentAsync()
    {
        return await CoreWebView2Environment.CreateAsync(null, UserDataFolder);
    }

    public static async Task<MuseCredential?> CheckAuthAsync(WebView2 webView, MuseSession session)
    {
        if (webView.CoreWebView2 is null)
        {
            throw new MuseAuthException(MuseAuthKind.NetworkUnavailable);
        }

        var source = webView.CoreWebView2.Source;
        if (!source.StartsWith("https://muse.ai/", StringComparison.OrdinalIgnoreCase))
        {
            throw new MuseAuthException(MuseAuthKind.LoginRequired);
        }

        // WebView2 的 ExecuteScriptAsync 不等待异步脚本的 Promise，
        // 不能直接靠脚本返回值拿 fetch 结果（上一版因此只拿到空对象 {}）。
        // 改法：JS 同步启动 fetch，把结果写进 window 变量，C# 轮询
        // 这个变量直到有值或超时，fetch 本身是 .then/.catch 链。
        const string script = """
            (() => {
              window.__museQuotaAuthResult = null;
              const controller = new AbortController();
              setTimeout(() => controller.abort(), 10000);
              fetch('/api/auth/check', {
                method: 'POST', credentials: 'include', cache: 'no-store', signal: controller.signal
              }).then(async (response) => {
                let json = null;
                try { json = await response.json(); } catch (e) { json = null; }
                const payload = {};
                if (json && typeof json === 'object') {
                  for (const key of ['outcome', 'access_token', 'viewer_id', 'session_binding_id', 'type', 'reason', 'status']) {
                    if (Object.prototype.hasOwnProperty.call(json, key)) payload[key] = json[key];
                  }
                }
                window.__museQuotaAuthResult = JSON.stringify({ httpStatus: response.status, payload: payload });
              }).catch((e) => {
                window.__museQuotaAuthResult = JSON.stringify({ httpStatus: 0, payload: { type: 'fetchFailed', reason: e && e.name ? e.name : 'unknown' } });
              });
              return 'started';
            })()
            """;

        await webView.ExecuteScriptAsync(script);

        // 轮询 window 变量：同步脚本的返回值是确定的字符串或 null，
        // 不再依赖异步返回值。15 秒内没值就是网络超时。
        string? jsonText = null;
        var deadline = DateTimeOffset.UtcNow.AddSeconds(15);
        while (DateTimeOffset.UtcNow < deadline)
        {
            if (webView.CoreWebView2 is null)
            {
                throw new MuseAuthException(MuseAuthKind.NetworkUnavailable);
            }

            var rawPoll = await webView.ExecuteScriptAsync("window.__museQuotaAuthResult");
            try
            {
                using var pollDoc = JsonDocument.Parse(rawPoll);
                if (pollDoc.RootElement.ValueKind == JsonValueKind.String)
                {
                    var value = pollDoc.RootElement.GetString();
                    if (!string.IsNullOrWhiteSpace(value))
                    {
                        jsonText = value;
                        break;
                    }
                }
                // ValueKind 是 Null 时表示 fetch 还没完成，继续轮询。
            }
            catch
            {
                // 轮询解析失败时不直接判错，等下一轮或超时。
            }

            await Task.Delay(250);
        }

        if (string.IsNullOrWhiteSpace(jsonText))
        {
            MuseDiagnostics.Log("auth timeout: window.__museQuotaAuthResult never set");
            throw new MuseAuthException(MuseAuthKind.NetworkUnavailable);
        }

        using (var doc = JsonDocument.Parse(jsonText))
        {
            var root = doc.RootElement;

            if (!root.TryGetProperty("httpStatus", out var statusEl)
                || !root.TryGetProperty("payload", out var payload)
                || payload.ValueKind != JsonValueKind.Object)
            {
                MuseDiagnostics.Log($"auth invalid: script result keys=[{MuseDiagnostics.DescribeKeys(root)}]");
                throw new MuseAuthException(MuseAuthKind.InvalidResponse);
            }

            var status = statusEl.GetInt32();
            string? GetStr(string name) =>
                payload.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
                    ? v.GetString() : null;

            // 只记结构不记值：状态码、字段名、outcome/type/reason、
            // 有无令牌（布尔值）、binding 的类型，令牌与账号 id 一律不记。
            MuseDiagnostics.Log($"auth: httpStatus={status} payload=[{MuseDiagnostics.DescribeKeys(payload)}] "
                + $"outcome={GetStr("outcome") ?? "(none)"} type={GetStr("type") ?? "(none)"} "
                + $"reason={GetStr("reason") ?? "(none)"} hasToken={!string.IsNullOrWhiteSpace(GetStr("access_token"))} "
                + $"bindingKind={(payload.TryGetProperty("session_binding_id", out var bk) ? bk.ValueKind.ToString() : "(missing)")}");

            if (status == 401)
            {
                throw new MuseAuthException(MuseAuthKind.LoginRequired, 401);
            }

            if (status == 403 && GetStr("type") == "checkpointRequired")
            {
                throw new MuseAuthException(MuseAuthKind.CheckpointRequired, 403);
            }

            if (status == 403 && GetStr("type") == "hatchAdmissionInvalidated"
                && GetStr("reason") is "entitlement" or "activation")
            {
                throw new MuseAuthException(MuseAuthKind.AccessRestricted, 403);
            }

            if (status < 200 || status >= 300)
            {
                throw new MuseAuthException(MuseAuthKind.RequestRejected, status);
            }

            if (GetStr("outcome") != "validated")
            {
                throw new MuseAuthException(MuseAuthKind.LoginRequired);
            }

            var viewerId = GetStr("viewer_id");
            if (string.IsNullOrWhiteSpace(viewerId))
            {
                throw new MuseAuthException(MuseAuthKind.InvalidResponse);
            }

            string? binding = null;
            if (payload.TryGetProperty("session_binding_id", out var bindingEl)
                && bindingEl.ValueKind == JsonValueKind.String)
            {
                binding = bindingEl.GetString();
            }
            else if (payload.TryGetProperty("session_binding_id", out var nullEl)
                && nullEl.ValueKind != JsonValueKind.Null)
            {
                throw new MuseAuthException(MuseAuthKind.InvalidResponse);
            }

            var fingerprint = MuseCredential.FingerprintFor(viewerId, binding);
            var token = GetStr("access_token");
            if (!string.IsNullOrWhiteSpace(token))
            {
                return new MuseCredential(token, fingerprint);
            }

            // 本次没给新令牌：只有指纹与旧凭据完全一致时才复用旧令牌。
            if (session.Credential is { } previous && previous.Fingerprint == fingerprint)
            {
                return null;
            }

            throw new MuseAuthException(MuseAuthKind.TokenUnavailable);
        }
    }
}
