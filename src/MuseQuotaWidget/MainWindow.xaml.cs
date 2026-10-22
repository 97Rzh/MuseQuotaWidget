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

        _ = LoadQuotaAsync();
    }

    private void SetRefreshInterval(int minutes)
    {
        _refreshIntervalMinutes = Math.Clamp(minutes, 1, 60);
        _refreshTimer.Interval = TimeSpan.FromMinutes(_refreshIntervalMinutes);
        SettingsStore.SaveIntervalMinutes(_refreshIntervalMinutes);
        if (_lastGood is { } last)
        {
            Show(last, "Muse 直连");
        }
        else
        {
            StatusText.Text = $"未登录 Muse，右键登录 · 每 {_refreshIntervalMinutes} 分钟刷新";
        }
    }

    private async Task LoadQuotaAsync()
    {
        if (!_museSession.HasToken)
        {
            StatusText.Text = _lastGood is null
                ? "未登录 Muse，右键登录"
                : "未登录 Muse，显示上次数据";
            return;
        }

        try
        {
            var museData = await _museSession.FetchQuotaAsync();
            _lastGood = museData;
            Show(museData, "Muse 直连");
        }
        catch (MuseAuthException ex) when (ex.Kind is MuseAuthKind.LoginRequired
            or MuseAuthKind.AccountChanged or MuseAuthKind.TokenUnavailable)
        {
            // 登录失效时清掉内存令牌，不再用旧数据冒充新数据。
            _museSession.Clear();
            StatusText.Text = _lastGood is null
                ? "Muse 登录已失效，请右键重新登录"
                : "Muse 登录已失效，显示上次数据，请右键重新登录";
        }
        catch (MuseAuthException ex)
        {
            // 网络、限流等临时失败：不丢令牌，下次定时刷新再试。
            StatusText.Text = _lastGood is null
                ? $"额度读取失败：{ex.MessageZh}"
                : $"额度读取失败，显示上次数据：{ex.MessageZh}";
        }
    }

    private void Show(QuotaData data, string source)
    {
        var remaining = Math.Clamp(data.Remaining, 0, 100);
        RemainingText.Text = $"{remaining:0}%";
        RemainingBar.Value = remaining;
        RemainingText.Foreground = remaining switch
        {
            < 20 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xF8, 0x71, 0x71)),
            < 50 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xFB, 0xBF, 0x24)),
            _ => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x4A, 0xDE, 0x80)),
        };

        PlanText.Text = data.Plan;
        DetailText.Text = $"已用 {data.UsedPercent:0}%";

        if (data.WeeklyResetAt is { } reset)
        {
            var countdown = reset - DateTimeOffset.Now;
            var countdownText = countdown.TotalSeconds <= 0
                ? "已过重置时间，请更新数据"
                : countdown.TotalDays >= 1
                    ? $"还有 {countdown.Days} 天 {countdown.Hours} 小时"
                    : $"还有 {countdown.Hours} 小时 {countdown.Minutes} 分钟";
            ResetText.Text = $"{reset:MM 月 dd 日 HH:mm} 重置 · {countdownText}";
        }
        else
        {
            ResetText.Text = "重置时间未知";
        }

        // 额外词元单独一行、单独一条进度条，不再挤在周额度那行里。
        // 注意：这里显示的是 hatch-api 的 topup_balance 换算值，
        // 与 agent 侧 subscription-status 说的 31B 对不上时不要硬凑，
        // 见 README 的“额外词元为什么是 12.4 亿”一节与诊断日志。
        AdditionalText.Text = string.IsNullOrWhiteSpace(data.AdditionalTokensLeft)
            ? "未知"
            : $"剩余 {data.AdditionalTokensLeft}";
        AdditionalBar.Value = Math.Clamp(100 - data.AdditionalTokensUsedPercent, 0, 100);

        StatusText.Text = data.UpdatedAt is { } updated
            ? $"数据更新于 {updated:MM 月 dd 日 HH:mm} · 来源：{source} · 每 {_refreshIntervalMinutes} 分钟刷新"
            : $"来源：{source} · 每 {_refreshIntervalMinutes} 分钟刷新";
    }

    private void Card_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ButtonState == MouseButtonState.Pressed)
        {
            DragMove();
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await LoadQuotaAsync();

    private void Login_Click(object sender, RoutedEventArgs e)
    {
        var login = new LoginWindow(_museSession) { Owner = this };
        if (login.ShowDialog() == true && login.VerifiedQuota is { } quota)
        {
            _lastGood = quota;
            Show(quota, "Muse 直连");
        }
    }

    private void Logout_Click(object sender, RoutedEventArgs e)
    {
        // 只清内存里的令牌与指纹，不删 WebView2 数据文件夹：
        // 网页登录 Cookie 仍在本地，下次打开登录窗口时若会话未过期
        // 可直接验证，无需重新输入密码。彻底退出请手动删除
        // %LOCALAPPDATA%\MuseQuotaWidget\WebView2 文件夹。
        _museSession.Clear();
        StatusText.Text = "已断开 Muse 额度读取；网页登录 Cookie 仍在本地，下次登录无需重新输入密码。";
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
            StatusText.Text = "暂无诊断日志：请先在登录窗口点一次“验证登录并读取额度”。";
        }
    }

    private void Exit_Click(object sender, RoutedEventArgs e) => Close();
}
