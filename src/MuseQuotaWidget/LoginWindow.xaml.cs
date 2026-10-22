using System.IO;
using System.Text.Json;
using System.Windows;
using Microsoft.Web.WebView2.Core;
using MuseQuotaWidget.Services;

namespace MuseQuotaWidget;

/// <summary>
/// 内置登录窗口：参照 ai-quota 的 MuseWebSession（macOS WKWebView），
/// 用 WPF + WebView2 重写。WebView2 的数据文件夹独立于 Edge 与系统浏览器，
/// 也独立于 Muse 原生应用的登录状态；登录 Cookie 持久化在这个文件夹里，
/// 下次打开登录窗口时若会话未过期可直接验证，无需重新输入密码。
/// 令牌本身只进 MuseSession 的内存，窗口关闭也不会把它写盘。
/// 只有在真实额度响应通过解码器后，窗口才算验证成功并关闭；
/// 失败时窗口保持打开，可重试。
/// </summary>
public partial class LoginWindow : Window
{
    private readonly MuseSession _session;
    private bool _initialized;

    public Models.QuotaData? VerifiedQuota { get; private set; }
    public bool Verified => VerifiedQuota is not null;

    public LoginWindow(MuseSession session)
    {
        InitializeComponent();
        _session = session;
        Loaded += async (_, _) => await InitializeAsync();
    }

    private async Task InitializeAsync()
    {
        if (_initialized)
        {
            return;
        }

        _initialized = true;
        try
        {
            var userDataFolder = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "MuseQuotaWidget", "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(null, userDataFolder);
            await WebView.EnsureCoreWebView2Async(environment);
            WebView.CoreWebView2.Navigate("https://muse.ai/");
        }
        catch (Exception ex)
        {
            // 最常见的原因是本机没有 WebView2 Runtime。
            StatusText.Text = "无法启动内置浏览器（WebView2 Runtime 可能未安装）：" + ex.Message;
            VerifyButton.IsEnabled = false;
        }
    }

    private async void VerifyButton_Click(object sender, RoutedEventArgs e)
    {
        VerifyButton.IsEnabled = false;
        var stage = "登录检查";
        try
        {
            StatusText.Text = "正在检查 Muse 网页登录…";
            var credential = await CheckAuthAsync();
            if (credential is not null)
            {
                _session.SetCredential(credential);
            }
            else if (!_session.HasToken)
            {
                throw new MuseAuthException(MuseAuthKind.TokenUnavailable);
            }
            // credential 为 null 且已有同指纹旧令牌时，复用旧令牌
            // （ai-quota 注明：前端在重验证时可能不返回 access_token）。

            stage = "额度读取";
            StatusText.Text = "网页登录已通过，正在读取真实额度…";
            var quota = await _session.FetchQuotaAsync();
            VerifiedQuota = quota;
            DialogResult = true;
            Close();
        }
        catch (MuseAuthException ex)
        {
            if (ex.Kind is MuseAuthKind.LoginRequired or MuseAuthKind.AccountChanged
                or MuseAuthKind.TokenUnavailable or MuseAuthKind.InvalidResponse)
            {
                // 身份不确定时不保留旧令牌，避免把别人的额度当成自己的。
                _session.Clear();
            }

            // 阶段写进提示里：下次再报无法识别时，先看是登录检查
            // 还是额度读取那一步，诊断日志里也有对应的结构记录。
            StatusText.Text = $"验证未通过（{stage}）：{ex.MessageZh}（诊断日志：右键悬浮窗 → 打开诊断日志）";
            VerifyButton.IsEnabled = true;
        }
        catch (Exception ex)
        {
            StatusText.Text = $"验证未通过（{stage}）：网络请求失败或超时。请稍后重试。（{ex.Message}）";
            VerifyButton.IsEnabled = true;
        }
    }

    /// <summary>
    /// 在 WebView 里同源执行一次 POST /api/auth/check（ai-quota 的做法），
    /// 只取 outcome / access_token / viewer_id / session_binding_id /
    /// type / reason / status 这几个字段，不取 Cookie，不把令牌发给别处。
    /// 返回 null 表示本次未拿到新令牌，调用方按指纹决定是否复用旧令牌。
    /// </summary>
    private async Task<MuseCredential?> CheckAuthAsync()
    {
        if (WebView.CoreWebView2 is null)
        {
            throw new MuseAuthException(MuseAuthKind.NetworkUnavailable);
        }

        var source = WebView.CoreWebView2.Source;
        if (!source.StartsWith("https://muse.ai/", StringComparison.OrdinalIgnoreCase))
        {
            throw new MuseAuthException(MuseAuthKind.LoginRequired);
        }

        // 关键修正：WebView2 的 ExecuteScriptAsync 不等待异步脚本的
        // Promise，上一版的 async IIFE 在这里只返回了一个空对象 {}，
        // 诊断日志里的 script result keys=[(empty object)] 就是它。
        // ai-quota 的 Swift callAsyncJavaScript 会等异步 JS，WebView2
        // 不会，所以不能直接靠脚本返回值拿 fetch 结果。
        // 改法：JS 同步启动 fetch，把结果写进 window 变量，C# 轮询
        // 这个变量直到有值或超时，fetch 本身是 .then/.catch 链，
        // 不依赖 C# 等待 Promise。
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

        await WebView.ExecuteScriptAsync(script);

        // 轮询 window 变量：同步脚本的返回值是确定的字符串或 null，
        // 不再依赖异步返回值。15 秒内没值就是网络超时。
        string? jsonText = null;
        var deadline = DateTimeOffset.UtcNow.AddSeconds(15);
        while (DateTimeOffset.UtcNow < deadline)
        {
            if (WebView.CoreWebView2 is null)
            {
                throw new MuseAuthException(MuseAuthKind.NetworkUnavailable);
            }

            var rawPoll = await WebView.ExecuteScriptAsync("window.__museQuotaAuthResult");
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
            if (_session.Credential is { } previous && previous.Fingerprint == fingerprint)
            {
                return null;
            }

            throw new MuseAuthException(MuseAuthKind.TokenUnavailable);
        }
    }
}
