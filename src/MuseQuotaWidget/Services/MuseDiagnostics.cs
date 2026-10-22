using System.IO;
using System.Text.Json;

namespace MuseQuotaWidget.Services;

/// <summary>
/// 本地诊断日志：默认只记“结构”，不记“值”。
/// 记的东西：时间、阶段、HTTP 状态、返回体的字段名、字段类型、
/// outcome / type / reason / state 这类状态词、有无令牌（布尔值）。
/// 绝不记：访问令牌、viewer_id、session_binding_id、Cookie、
/// 任何能用来冒充登录的值。
/// 例外：MuseSession.LogQuotaNumbers 那一行会记额度数值本身
/// （百分比、词元余额等用户自己的额度，不是凭据），专门用于对数；
/// 日志只写本机，不上传、不进仓库，用户自己决定要不要发出来。
/// </summary>
public static class MuseDiagnostics
{
    public static string LogPath { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "MuseQuotaWidget", "muse-debug.log");

    public static void Log(string message)
    {
        try
        {
            var dir = Path.GetDirectoryName(LogPath);
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }

            File.AppendAllText(LogPath,
                $"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss} {message}{Environment.NewLine}");
        }
        catch
        {
            // 诊断日志写失败时不影响正常流程。
        }
    }

    /// <summary>返回一个 JSON 对象的“字段名:类型”列表，例如 usage:object, state:string。</summary>
    public static string DescribeKeys(JsonElement obj)
    {
        if (obj.ValueKind != JsonValueKind.Object)
        {
            return $"(not object: {obj.ValueKind})";
        }

        var parts = new List<string>();
        foreach (var prop in obj.EnumerateObject())
        {
            parts.Add($"{prop.Name}:{prop.Value.ValueKind}");
        }

        return parts.Count == 0 ? "(empty object)" : string.Join(", ", parts);
    }
}
