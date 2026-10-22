using System.Windows;
using System.Windows.Input;
using System.Windows.Threading;
using MuseQuotaWidget.Models;
using MuseQuotaWidget.Services;

namespace MuseQuotaWidget;

public partial class MainWindow : Window
{
    private readonly MuseSession _museSession = new();
    private readonly DispatcherTimer _refreshTimer;
    private int _refreshIntervalMinutes;
    // 仅内存里的上次成功快照：刷新失败时继续显示它并提示，
    // 不会把它写盘，也不会把它当成新数据。
    private QuotaData? _lastGood;

    public MainWindow()
    {
        InitializeComponent();

        // 刷新频率默认 5 分钟，可在设置窗里拖滑块改（1-60 分钟），
        // 保存在本地 settings.json；只走 Muse 直连（内置登录）。
        // 读额度接口不是对话，不产生对话 token。
        _refreshIntervalMinutes = SettingsStore.LoadIntervalMinutes();
        _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMinutes(_refreshIntervalMinutes) };
        _refreshTimer.Tick += async (_, _) => await LoadQuotaAsync();
        _refreshTimer.Start();

        _ = AutoLoginAndLoadAsync();
    }

    /// <summary>
    /// 启动（和手动刷新）时先后台自动登录：用上次登录留下的 Cookie
    /// 在离屏窗口里静默换令牌，成功就直接显示额度，用户不用再点登录。
    /// 只有 Cookie 已过期、被清除或 Muse 要求重新验证时才会失败，
    /// 那时落到 LoadQuotaAsync 显示“未登录”，用户右键手动登录即可。
    /// 定时刷新不走这里，避免会话过期后每 5 分钟都弹一个后台窗。
    /// </summary>
    private async Task AutoLoginAndLoadAsync()
    {
        if (!_museSession.HasToken)
        {
            TimeText.Text = "自动登录中…";
            try
            {
                var background = new BackgroundLoginWindow(_museSession);
                var credential = await background.TryAuthenticateAsync();
                if (credential is not null)
                {
                    _museSession.SetCredential(credential);
                }
            }
            catch
            {
                // 后台登录失败不弹窗、不崩，只落到手动登录。
            }
        }

        await LoadQuotaAsync();
    }

    private void SetRefreshInterval(int minutes)
    {
        _refreshIntervalMinutes = Math.Clamp(minutes, 1, 60);
        _refreshTimer.Interval = TimeSpan.FromMinutes(_refreshIntervalMinutes);
        SettingsStore.SaveIntervalMinutes(_refreshIntervalMinutes);
        if (_lastGood is { } last)
        {
            Show(last);
        }
        else
        {
            TimeText.Text = "未登录";
        }
    }

    private async Task LoadQuotaAsync()
    {
        if (!_museSession.HasToken)
        {
            // 未登录时只显示“未登录”，百分比保持上次的（或初始的 —），
            // 不拿旧数据冒充新数据。
            TimeText.Text = "未登录";
            return;
        }

        try
        {
            var museData = await _museSession.FetchQuotaAsync();
            _lastGood = museData;
            Show(museData);
        }
        catch (MuseAuthException ex) when (ex.Kind is MuseAuthKind.LoginRequired
            or MuseAuthKind.AccountChanged or MuseAuthKind.TokenUnavailable)
        {
            // 登录失效时清掉内存令牌；时间行只写短提示，
            // 百分比与条保持上次成功值，不清空。
            _museSession.Clear();
            TimeText.Text = "登录已失效";
        }
        catch (MuseAuthException)
        {
            // 网络、限流等临时失败：不丢令牌，下次定时刷新再试。
            TimeText.Text = "读取失败";
        }
    }

    private void Show(QuotaData data)
    {
        // 极简版：只显示周额度剩余百分比 + 一条，不显示标题、
        // 计划、已用、额外词元等任何字样。时间行只放刷新时间
        // （每周额度重置时间），不带任何前缀字样。
        var remaining = Math.Clamp(data.Remaining, 0, 100);
        RemainingText.Text = $"{remaining:0}%";
        RemainingBar.Value = remaining;
        var brush = remaining switch
        {
            < 20 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xF8, 0x71, 0x71)),
            < 50 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xFB, 0xBF, 0x24)),
            _ => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x4A, 0xDE, 0x80)),
        };
        RemainingText.Foreground = brush;
        RemainingBar.Foreground = brush;

        // 刷新时间：解码时已转本地时间，这里再转一次是幂等的，
        // 保证 UTC 返回的时间显示为本地时间（+8），不显示 UTC。
        TimeText.Text = data.WeeklyResetAt is { } reset
            ? $"{reset.ToLocalTime():MM-dd HH:mm}"
            : string.Empty;
    }

    private void Card_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ButtonState == MouseButtonState.Pressed)
        {
            DragMove();
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        // 手动刷新时若令牌已丢，也先试一次后台自动登录，
        // Cookie 还在的话就不用用户再点登录；定时刷新不走这里。
        if (_museSession.HasToken)
        {
            await LoadQuotaAsync();
        }
        else
        {
            await AutoLoginAndLoadAsync();
        }
    }

    private void Login_Click(object sender, RoutedEventArgs e)
    {
        var login = new LoginWindow(_museSession) { Owner = this };
        if (login.ShowDialog() == true && login.VerifiedQuota is { } quota)
        {
            _lastGood = quota;
            Show(quota);
        }
    }

    private void Logout_Click(object sender, RoutedEventArgs e)
    {
        // 只清内存里的令牌与指纹，不删 WebView2 数据文件夹：
        // 网页登录 Cookie 仍在本地，下次打开登录窗口时若会话未过期
        // 可直接验证，无需重新输入密码。彻底退出请手动删除
        // %LOCALAPPDATA%\MuseQuotaWidget\WebView2 文件夹。
        _museSession.Clear();
        TimeText.Text = "未登录";
    }

    private void Settings_Click(object sender, RoutedEventArgs e)
    {
        var settings = new SettingsWindow(_refreshIntervalMinutes) { Owner = this };
        if (settings.ShowDialog() == true)
        {
            SetRefreshInterval(settings.SelectedMinutes);
        }
    }

    private void Topmost_Click(object sender, RoutedEventArgs e)
    {
        Topmost = TopmostMenuItem.IsChecked == true;
    }

    private void OpenDebugLog_Click(object sender, RoutedEventArgs e)
    {
        // 诊断日志只在本机，里面没有令牌与账号 id；其中 quota numbers
        // 那一行会记额度数值本身（用于对额外 token 的数），用户自愿发。
        if (System.IO.File.Exists(MuseDiagnostics.LogPath))
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(MuseDiagnostics.LogPath)
            {
                UseShellExecute = true,
            });
        }
        else
        {
            TimeText.Text = "无诊断日志";
        }
    }

    private void Exit_Click(object sender, RoutedEventArgs e) => Close();
}
