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
    private readonly DispatcherTimer _refreshTimer;
    private QuotaData? _lastGood;

    public MainWindow()
    {
        InitializeComponent();

        var dataPath = Path.Combine(AppContext.BaseDirectory, "quota.json");
        _provider = new FileQuotaProvider(dataPath);

        // 每 5 分钟重读一次 quota.json：改完文件不用重启悬浮窗。
        _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMinutes(5) };
        _refreshTimer.Tick += (_, _) => LoadQuota();
        _refreshTimer.Start();

        LoadQuota();
    }

    private void LoadQuota()
    {
        var data = _provider.TryLoad(out var error);
        if (data is not null)
        {
            _lastGood = data;
            Show(data);
            return;
        }

        // 读失败时：有旧数据就继续显示旧数据，只在底部提示；没旧数据才显示错误。
        StatusText.Text = _lastGood is null
            ? $"读不到额度数据：{error}"
            : $"数据文件读取失败，显示上次数据：{error}";
    }

    private void Show(QuotaData data)
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
            ? $"数据更新于 {updated:MM 月 dd 日 HH:mm} · 拖动可移动，右键有菜单"
            : "拖动可移动，右键有菜单";
    }

    private void Card_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ButtonState == MouseButtonState.Pressed)
        {
            DragMove();
        }
    }

    private void Refresh_Click(object sender, RoutedEventArgs e) => LoadQuota();

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
