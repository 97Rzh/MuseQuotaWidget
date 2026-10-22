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

        // 返回 JSON 字符串（而不是对象）：WebView2 对异步脚本返回值的
        // 序列化方式不稳定，返回字符串时解析路径是确定的。
        // fetch 本身失败时也不让 Promise 直接拒绝，改成返回结构化错误，
        // 否则 ExecuteScriptAsync 只会给一个 null，无法区分是哪一步。
        const string script = """
            (async () => {
              const controller = new AbortController();
              const timeout = setTimeout(() => controller.abort(), 10000);
              try {
                const response = await fetch('/api/auth/check', {
                  method: 'POST', credentials: 'include', cache: 'no-store', signal: controller.signal
                });
                let json = null;
                try { json = await response.json(); } catch (e) { json = null; }
                const payload = {};
                if (json && typeof json === 'object') {
                  for (const key of ['outcome', 'access_token', 'viewer_id', 'session_binding_id', 'type', 'reason', 'status']) {
                    if (Object.prototype.hasOwnProperty.call(json, key)) payload[key] = json[key];
                  }
                }
                return JSON.stringify({ httpStatus: response.status, payload: payload });
              } catch (e) {
                return JSON.stringify({ httpStatus: 0, payload: { type: 'fetchFailed', reason: e && e.name ? e.name : 'unknown' } });
              } finally {
                clearTimeout(timeout);
              }
            })()
            """;

        var raw = await WebView.ExecuteScriptAsync(script);
        // ExecuteScriptAsync 返回的是 JS 结果的 JSON 序列化；若结果本身
        // 是字符串，再解析一层。
        string jsonText;
        try
        {
            using var first = JsonDocument.Parse(raw);
            jsonText = first.RootElement.ValueKind == JsonValueKind.String
                ? first.RootElement.GetString() ?? string.Empty
                : raw;
        }
        catch
        {
            throw new MuseAuthException(MuseAuthKind.InvalidResponse);
        }

        if (string.IsNullOrWhiteSpace(jsonText))
        {
            throw new MuseAuthException(MuseAuthKind.InvalidResponse);
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
