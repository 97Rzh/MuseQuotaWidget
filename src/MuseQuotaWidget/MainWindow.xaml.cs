using System.Windows;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using MuseQuotaWidget.Models;
using MuseQuotaWidget.Services;

namespace MuseQuotaWidget;

public partial class MainWindow : Window
{
    private readonly MuseSession _museSession = new();
    private readonly DispatcherTimer _refreshTimer;
    private int _refreshIntervalMinutes;
    // 节奏白点在刻度上的位置（0 = 最左 Δ=-25，1 = 最右 Δ=+25），
    // 刻度宽度变化时（窗口布局完成后）靠它重新定位白点。
    private double _paceFraction = 0.5;
    // 仅内存里的上次成功快照：刷新失败时继续显示它并提示，
    // 不会把它写盘，也不会把它当成新数据。
    private QuotaData? _lastGood;
    // 设置面板是否展开；展开时窗口变宽、额度区缩到左上角。
    private bool _isSettingsExpanded;
    // 面板滑块初始化时不触发保存与计时器变更，只更新显示。
    private bool _suppressSliderApply;

    public MainWindow()
    {
        InitializeComponent();

        // 刷新频率默认 5 分钟，面板里的滑块可拖 1-60 分钟，
        // 拖动立即生效并保存到本地 settings.json；只走 Muse 直连。
        // 读额度接口不是对话，不产生对话 token。
        _refreshIntervalMinutes = SettingsStore.LoadIntervalMinutes();
        _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMinutes(_refreshIntervalMinutes) };
        _refreshTimer.Tick += async (_, _) => await LoadQuotaAsync();
        _refreshTimer.Start();

        TopmostCheckBox.IsChecked = Topmost;
        _suppressSliderApply = true;
        IntervalSliderPanel.Value = _refreshIntervalMinutes;
        IntervalValueTextPanel.Text = $"每 {_refreshIntervalMinutes} 分钟刷新";
        _suppressSliderApply = false;
        UpdateLoginStatus();

        _ = AutoLoginAndLoadAsync();
    }

    /// <summary>
    /// 启动（和手动刷新）时先后台自动登录：用上次登录留下的 Cookie
    /// 在离屏窗口里静默换令牌，成功就直接显示额度，用户不用再点登录。
    /// 只有 Cookie 已过期、被清除或 Muse 要求重新验证时才会失败，
    /// 那时落到 LoadQuotaAsync 显示“未登录”，用户点齿轮 → 登录即可。
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
        // 没有上次快照时不碰时间行：面板滑块初始化或启动时
        // 时间行可能是“自动登录中…”，不能被它覆盖成“未登录”。
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
            UpdateLoginStatus();
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

        ShowPace(data, remaining);
        UpdateLoginStatus();
    }

    /// <summary>
    /// 第二版用量节奏控件：只显示与平均线的偏差，不重复显示已用%。
    /// 平均线：周期按 7 天计，起点 = 重置时间 - 7 天，
    /// 平均应为 = 已过天数 / 7 × 100%；差值 Δ = 已用% - 平均应为%。
    /// 颜色只看 Δ（百分点，不用比值，避免周期初期比值爆炸）：
    /// Δ ≤ -5 绿、-5 ~ +5 黄持平、+5 ~ +20 橙、≥ +20 深红。
    /// 白点位置：Δ 钳制到 [-25, +25] 再映射到刻度 0 ~ 100%，中央 = Δ0。
    /// 预计用完：按当前速度（已用 / 已过天数）外推，不是承诺，
    /// 速度一变它就变；已过天数为 0 时算不出速度，只写快/慢。
    /// 重置时间拿不到时整个节奏面板隐藏。
    /// 注意：节奏按现在这一刻算，不按快照的更新时间算，
    /// 所以时间过去后即使额度没刷新，节奏也会跟着动。
    /// </summary>
    private void ShowPace(QuotaData data, double remaining)
    {
        if (data.WeeklyResetAt is not { } reset)
        {
            PacePanel.Visibility = Visibility.Collapsed;
            return;
        }

        var resetLocal = reset.ToLocalTime();
        var cycleStart = resetLocal.AddDays(-7);
        var elapsedDays = Math.Clamp((DateTimeOffset.Now - cycleStart).TotalDays, 0, 7);
        var expected = elapsedDays / 7 * 100;
        var used = 100 - remaining;
        var delta = used - expected;

        var paceBrush = delta switch
        {
            <= -20 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x22, 0xC5, 0x5E)),
            <= -5 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x4A, 0xDE, 0x80)),
            <= 5 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xEA, 0xB3, 0x08)),
            <= 20 => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xF9, 0x73, 0x16)),
            _ => new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xEF, 0x44, 0x44)),
        };
        PaceText.Foreground = paceBrush;

        var paceLabel = delta switch
        {
            <= -5 => $"慢 {Math.Abs(delta):0}%",
            >= 5 => $"快 {delta:0}%",
            _ => "持平",
        };

        string? projected = null;
        if (elapsedDays > 0)
        {
            var speed = used / elapsedDays;
            if (speed <= 0)
            {
                projected = "预计重置时还剩 100%";
            }
            else
            {
                var daysTo100 = 100 / speed;
                if (daysTo100 <= 7)
                {
                    var daysEarly = 7 - daysTo100;
                    projected = daysEarly <= 0.05
                        ? "预计正好在重置时用完"
                        : $"预计提前 {daysEarly:0.0} 天用完";
                }
                else
                {
                    var remainingAtReset = Math.Clamp(100 - speed * 7, 0, 100);
                    projected = $"预计重置时还剩 {remainingAtReset:0}%";
                }
            }
        }

        PaceText.Text = projected is null ? paceLabel : $"{paceLabel} · {projected}";

        _paceFraction = (Math.Clamp(delta, -25, 25) + 25) / 50;
        PacePanel.Visibility = Visibility.Visible;
        PacePanel.UpdateLayout();
        PositionPaceDot();
    }

    /// <summary>
    /// 按 _paceFraction 定位白点：白点中心对准刻度上的对应位置，
    /// 两端钳制在刻度内。布局完成前 ActualWidth 为 0 时，
    /// 按窗口宽度（240 - 左右内边距 16×2 = 208）估算，
    /// 布局完成后的 SizeChanged 会再纠正一次。
    /// </summary>
    private void PositionPaceDot()
    {
        var scaleWidth = PaceScaleGrid.ActualWidth > 0 ? PaceScaleGrid.ActualWidth : 208;
        var marginLeft = Math.Clamp(_paceFraction * scaleWidth - PaceDot.Width / 2, 0, scaleWidth - PaceDot.Width);
        PaceDot.Margin = new Thickness(marginLeft, 0, 0, 0);
    }

    private void PaceScaleGrid_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (PacePanel.Visibility == Visibility.Visible)
        {
            PositionPaceDot();
        }
    }

    private void Card_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ButtonState != MouseButtonState.Pressed)
        {
            return;
        }

        // 点到按钮、复选框、滑块及其模板内的子元素时不拖动窗口，
        // 否则 DragMove 会抢走鼠标、导致齿轮与面板按钮点不下去。
        // 额度区空白处仍可拖动。
        var source = e.OriginalSource as DependencyObject;
        while (source is not null)
        {
            if (source is ButtonBase or System.Windows.Controls.CheckBox or System.Windows.Controls.Slider or Thumb)
            {
                return;
            }

            source = VisualTreeHelper.GetParent(source);
        }

        DragMove();
    }

    /// <summary>
    /// 齿轮按钮只在鼠标悬停到悬浮窗上时显示，平时不显示。
    /// 展开时也一样：鼠标离开后齿轮隐藏，再悬停回来又出现，
    /// 面板里的“完成”按钮是另一条收起路径，不依赖齿轮。
    /// </summary>
    private void Card_MouseEnter(object sender, MouseEventArgs e)
    {
        SettingsButton.Visibility = Visibility.Visible;
    }

    private void Card_MouseLeave(object sender, MouseEventArgs e)
    {
        SettingsButton.Visibility = Visibility.Collapsed;
    }

    /// <summary>
    /// 齿轮开关：展开时窗口从 240 变宽到 528，设置面板占 300 宽，
    /// 额度列自动剩 180 宽并缩到左上角；收起时恢复 240 与居中大字。
    /// 展开后不改额度数据本身，只改字号与对齐（见 SetQuotaMini），
    /// 刷新时 Show() 不碰字号与对齐，迷你状态不会被刷新打回原样。
    /// </summary>
    private void SettingsButton_Click(object sender, RoutedEventArgs e)
    {
        ToggleSettingsPanel();
    }

    private void Complete_Click(object sender, RoutedEventArgs e)
    {
        ToggleSettingsPanel();
    }

    private void ToggleSettingsPanel()
    {
        _isSettingsExpanded = !_isSettingsExpanded;
        if (_isSettingsExpanded)
        {
            Width = 528;
            SettingsPanel.Visibility = Visibility.Visible;
            SetQuotaMini(true);
            UpdateLoginStatus();
        }
        else
        {
            Width = 240;
            SettingsPanel.Visibility = Visibility.Collapsed;
            SetQuotaMini(false);
        }

        UpdateLayout();
        PositionPaceDot();
    }

    private void SetQuotaMini(bool mini)
    {
        RemainingText.FontSize = mini ? 28 : 44;
        RemainingText.HorizontalAlignment = mini ? HorizontalAlignment.Left : HorizontalAlignment.Center;
        TimeText.HorizontalAlignment = mini ? HorizontalAlignment.Left : HorizontalAlignment.Center;
        TimeText.FontSize = mini ? 10 : 11;
        PaceText.HorizontalAlignment = mini ? HorizontalAlignment.Left : HorizontalAlignment.Center;
        PaceText.FontSize = mini ? 10 : 12;
    }

    /// <summary>
    /// 面板里的登录状态与按钮可用性：已登录时登录按钮禁用、
    /// 退出登录可用；未登录时反过来。刷新按钮始终可用，
    /// 未登录时点它会先走后台自动登录。
    /// </summary>
    private void UpdateLoginStatus()
    {
        var loggedIn = _museSession.HasToken;
        LoginStatusText.Text = loggedIn ? "已登录" : "未登录";
        LoginStatusText.Foreground = loggedIn
            ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x4A, 0xDE, 0x80))
            : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0x9C, 0xA3, 0xAF));
        LoginButton.IsEnabled = !loggedIn;
        LogoutButton.IsEnabled = loggedIn;
    }

    private void IntervalSliderPanel_ValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (IntervalValueTextPanel is null)
        {
            return;
        }

        var minutes = (int)IntervalSliderPanel.Value;
        IntervalValueTextPanel.Text = $"每 {minutes} 分钟刷新";
        if (_suppressSliderApply)
        {
            return;
        }

        // 面板内滑块拖动立即生效并保存，不用再点确定/取消。
        SetRefreshInterval(minutes);
    }

    private void TopmostCheckBox_Click(object sender, RoutedEventArgs e)
    {
        Topmost = TopmostCheckBox.IsChecked == true;
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
        PacePanel.Visibility = Visibility.Collapsed;
        UpdateLoginStatus();
        // 退出登录不收起设置面板：用户能直接看到状态变回“未登录”，
        // 再点登录或点“完成”收起。
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
