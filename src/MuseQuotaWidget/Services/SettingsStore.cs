using System.IO;
using System.Text.Json;

namespace MuseQuotaWidget.Services;

/// <summary>
/// 本地设置：只存刷新频率（分钟），不存任何账号与令牌。
/// 文件在 %LOCALAPPDATA%\MuseQuotaWidget\settings.json，删了就恢复默认 5 分钟。
/// </summary>
public static class SettingsStore
{
    public const int DefaultIntervalMinutes = 5;

    private static string Path { get; } = System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "MuseQuotaWidget", "settings.json");

    public static int LoadIntervalMinutes()
    {
        try
        {
            if (!File.Exists(Path))
            {
                return DefaultIntervalMinutes;
            }

            using var doc = JsonDocument.Parse(File.ReadAllText(Path));
            if (doc.RootElement.ValueKind == JsonValueKind.Object
                && doc.RootElement.TryGetProperty("refreshIntervalMinutes", out var value)
                && value.ValueKind == JsonValueKind.Number
                && value.TryGetInt32(out var minutes))
            {
                return Math.Clamp(minutes, 1, 60);
            }
        }
        catch
        {
            // 设置文件坏了就用默认值，不崩。
        }

        return DefaultIntervalMinutes;
    }

    public static void SaveIntervalMinutes(int minutes)
    {
        try
        {
            var dir = System.IO.Path.GetDirectoryName(Path);
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }

            var json = JsonSerializer.Serialize(
                new { refreshIntervalMinutes = Math.Clamp(minutes, 1, 60) },
                new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(Path, json);
        }
        catch
        {
            // 设置保存失败不影响当前这次刷新。
        }
    }
}
