using System.IO;
using System.Text.Json;
using MuseQuotaWidget.Models;

namespace MuseQuotaWidget.Services;

/// <summary>
/// 从本地 quota.json 读额度快照。
/// 读不到或格式不对时返回 null，由调用方保留上一次的好数据并提示，
/// 绝不因为一份坏文件就让悬浮窗崩掉。
/// </summary>
public sealed class FileQuotaProvider
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    public string DataPath { get; }

    public FileQuotaProvider(string dataPath)
    {
        DataPath = dataPath;
    }

    public QuotaData? TryLoad(out string? error)
    {
        error = null;
        try
        {
            if (!File.Exists(DataPath))
            {
                error = $"找不到数据文件：{DataPath}";
                return null;
            }

            var json = File.ReadAllText(DataPath);
            var data = JsonSerializer.Deserialize<QuotaData>(json, JsonOptions);
            if (data is null)
            {
                error = "数据文件为空或无法解析。";
                return null;
            }

            return data;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return null;
        }
    }
}
