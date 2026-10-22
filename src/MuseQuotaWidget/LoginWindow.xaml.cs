using System.Windows;
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
            var environment = await MuseWebAuth.CreateEnvironmentAsync();
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
            var credential = await MuseWebAuth.CheckAuthAsync(WebView, _session);
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
            StatusText.Text = $"验证未通过（{stage}）：{ex.MessageZh}（诊断日志：点齿轮 → 打开诊断日志）";
            VerifyButton.IsEnabled = true;
        }
        catch (Exception ex)
        {
            StatusText.Text = $"验证未通过（{stage}）：网络请求失败或超时。请稍后重试。（{ex.Message}）";
            VerifyButton.IsEnabled = true;
        }
    }
}
