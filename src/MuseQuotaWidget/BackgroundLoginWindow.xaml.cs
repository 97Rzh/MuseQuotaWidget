using System.Windows;
using Microsoft.Web.WebView2.Core;
using MuseQuotaWidget.Services;

namespace MuseQuotaWidget;

/// <summary>
/// 后台登录窗：启动时自动登录就靠它，用户看不到它。
/// 做法：窗口离屏 + 透明显示（Opacity 0、移到屏幕外、任务栏不显示、
/// 不抢焦点），但 WebView2 仍在正常加载；用与可见登录窗完全相同的
/// WebView2 数据文件夹，所以上次登录留下的 Cookie 还在，
/// 加载 muse.ai 后直接用它换令牌，不用用户再点一次登录。
/// 换到令牌或确认换不到后立即关闭自己，不常驻。
/// 只有一种情况会失败后仍需手动登录：Cookie 已过期、被清除，
/// 或 Muse 要求重新验证——那时后台窗不会弹出来打扰用户，
/// 主窗口只显示“未登录”，用户点齿轮 → 登录即可。
/// </summary>
public partial class BackgroundLoginWindow : Window
{
    private readonly MuseSession _session;

    public BackgroundLoginWindow(MuseSession session)
    {
        InitializeComponent();
        _session = session;

        // 离屏隐藏：Show() 后仍不出现在用户眼前，也不抢焦点。
        Left = -10000;
        Top = -10000;
        Opacity = 0;
        ShowInTaskbar = false;
        ShowActivated = false;
        WindowStyle = WindowStyle.ToolWindow;
    }

    /// <summary>
    /// 静默换令牌：初始化 WebView2、加载 muse.ai、等导航完成、
    /// 用 Cookie 换令牌。成功返回新凭据（调用方负责存入会话），
    /// 失败返回 null 或抛错，调用方按失败处理，不弹窗。
    /// 无论成败，本方法结束时窗口都已关闭。
    /// </summary>
    public async Task<MuseCredential?> TryAuthenticateAsync()
    {
        try
        {
            Show();

            var environment = await MuseWebAuth.CreateEnvironmentAsync();
            await WebView.EnsureCoreWebView2Async(environment);

            var navigationDone = new TaskCompletionSource<bool>();
            void OnNavigationCompleted(object? sender, CoreWebView2NavigationCompletedEventArgs e)
            {
                navigationDone.TrySetResult(e.IsSuccess);
            }

            WebView.CoreWebView2.NavigationCompleted += OnNavigationCompleted;
            try
            {
                WebView.CoreWebView2.Navigate("https://muse.ai/");

                // 等导航完成，最多 20 秒；超时按失败处理，不卡住启动。
                var completed = await Task.WhenAny(navigationDone.Task, Task.Delay(TimeSpan.FromSeconds(20)));
                if (completed != navigationDone.Task || !navigationDone.Task.Result)
                {
                    MuseDiagnostics.Log("background login: navigation failed or timed out");
                    return null;
                }

                // 重定向链可能让第一次导航完成时地址还不是最终的 muse.ai，
                // 等地址落到 muse.ai 再换令牌，最多再等 5 秒。
                var addressDeadline = DateTimeOffset.UtcNow.AddSeconds(5);
                while (DateTimeOffset.UtcNow < addressDeadline
                    && !(WebView.CoreWebView2.Source?.StartsWith("https://muse.ai/",
                        StringComparison.OrdinalIgnoreCase) ?? false))
                {
                    await Task.Delay(250);
                }

                var credential = await MuseWebAuth.CheckAuthAsync(WebView, _session);
                if (credential is not null)
                {
                    return credential;
                }

                // 本次没给新令牌但指纹与旧凭据一致时，复用旧令牌；
                // 启动时旧凭据为空，所以这里正常情况下不会走到。
                return _session.Credential;
            }
            finally
            {
                WebView.CoreWebView2.NavigationCompleted -= OnNavigationCompleted;
            }
        }
        catch (MuseAuthException ex)
        {
            MuseDiagnostics.Log($"background login failed: {ex.Kind}");
            return null;
        }
        catch (Exception ex)
        {
            MuseDiagnostics.Log($"background login error: {ex.GetType().Name}");
            return null;
        }
        finally
        {
            Close();
        }
    }
}
