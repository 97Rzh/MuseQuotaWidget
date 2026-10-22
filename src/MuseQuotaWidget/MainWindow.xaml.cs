using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Input;
using System.Windows.Threading;
using MuseQuotaWidget.Models;
using MuseQuotaWidget.Services;

namespace MuseQuotaWidget;

public partial class MainWindow : Window
{
    private readonly FileQuotaProvider _provider;
    private readonly GitHubQuotaProvider _remoteProvider = new();
    private readonly MuseSession _museSession = new();
    private readonly DispatcherTimer _refreshTimer;
    private QuotaData? _lastGood;

    public MainWindow()
    {
        InitializeComponent();

        var dataPath = Path.Combine(AppContext.BaseDirectory, "quota.json");
        _provider = new FileQuotaProvider(dataPath);

        // 每 5 分钟刷新一次，优先级：Muse 直连（内置登录）>
        // GitHub 快照（需 github-token.txt）> 本地 quota.json。
        // Muse 直连这一步是读额度接口，不是对话，不产生对话 token。
        _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMinutes(5) };
        _refreshTimer.Tick += async (_, _) => await LoadQuotaAsync();
        _refreshTimer.Start();

        _ = LoadQuotaAsync();
    }

    private async Task LoadQuotaAsync()
    {
        // 第一路：Muse 直连（内置登录后内存里有令牌时才走）。
        if (_museSession.HasToken)
        {
            try
            {
                var museData = await _museSession.FetchQuotaAsync();
                _lastGood = museData;
                Show(museData, "Muse 直连");
                return;
            }
            catch (MuseAuthException ex) when (ex.Kind is MuseAuthKind.LoginRequired
                or MuseAuthKind.AccountChanged or MuseAuthKind.TokenUnavailable)
            {
                // 登录失效时清掉内存令牌，落到后面的回落路，并提示重新登录。
                _museSession.Clear();
                var (fallback, fallbackTokenPresent) = await _remoteProvider.TryLoadAsync();
                if (fallback is not null)
                {
                    _lastGood = fallback;
                    Show(fallback, "GitHub（Muse 登录已失效）");
                    return;
                }

                var fallbackLocal = _provider.TryLoad(out var fallbackError);
                if (fallbackLocal is not null)
                {
                    _lastGood = fallbackLocal;
                    Show(fallbackLocal, "本地文件（Muse 登录已失效，请重新登录）");
                    return;
                }

                StatusText.Text = _lastGood is null
                    ? $"读不到额度数据：{fallbackError}"
                    : "数据读取失败，显示上次数据（Muse 登录已失效，请重新登录）";
                return;
            }
            catch (MuseAuthException)
            {
                // 网络、限流等临时失败：不丢令牌，落到回落路，下次定时刷新再试直连。
            }
        }

        // 第二路：GitHub 这一步不耗 Muse 额度，只耗 GitHub API 调用次数。
        var (remote, tokenPresent) = await _remoteProvider.TryLoadAsync();
        if (remote is not null)
        {
            _lastGood = remote;
            Show(remote, "GitHub");
            return;
        }

        var local = _provider.TryLoad(out var error);
        if (local is not null)
        {
            _lastGood = local;
            Show(local, tokenPresent ? "本地文件（GitHub 拉取失败）" : "本地文件（未登录 Muse，右键登录）");
            return;
        }

        // 两路都失败时：有旧数据就继续显示旧数据，只在底部提示。
        StatusText.Text = _lastGood is null
            ? $"读不到额度数据：{error}"
            : $"数据读取失败，显示上次数据：{error}";
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
        DetailText.Text = $"周额度已用 {data.UsedPercent:0}% · 额外 tokens 剩余 {data.AdditionalTokensLeft}";

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

        StatusText.Text = data.UpdatedAt is { } updated
            ? $"数据更新于 {updated:MM 月 dd 日 HH:mm} · 来源：{source}"
            : $"来源：{source}";
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

    private void Topmost_Click(object sender, RoutedEventArgs e)
    {
        Topmost = TopmostMenuItem.IsChecked == true;
    }

    private void OpenDataFile_Click(object sender, RoutedEventArgs e)
    {
        Process.Start(new ProcessStartInfo(_provider.DataPath) { UseShellExecute = true });
    }

    private void Exit_Click(object sender, RoutedEventArgs e) => Close();
}
