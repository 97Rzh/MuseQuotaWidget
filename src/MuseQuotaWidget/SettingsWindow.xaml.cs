using System.Windows;
using System.Windows.Controls;

namespace MuseQuotaWidget;

/// <summary>
/// 刷新频率设置窗：滑块可拖动，1-60 分钟，拖动只改显示，
/// 点“确定”才真正生效并保存；点“取消”不改。
/// </summary>
public partial class SettingsWindow : Window
{
    public int SelectedMinutes { get; private set; }

    public SettingsWindow(int currentMinutes)
    {
        InitializeComponent();
        SelectedMinutes = currentMinutes;
        IntervalSlider.Value = currentMinutes;
        UpdateLabel();
    }

    private void IntervalSlider_ValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        UpdateLabel();
    }

    private void UpdateLabel()
    {
        if (IntervalValueText is null)
        {
            return;
        }

        IntervalValueText.Text = $"每 {(int)IntervalSlider.Value} 分钟刷新";
    }

    private void Ok_Click(object sender, RoutedEventArgs e)
    {
        SelectedMinutes = (int)IntervalSlider.Value;
        DialogResult = true;
        Close();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }
}
