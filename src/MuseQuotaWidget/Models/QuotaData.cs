using System.Text.Json.Serialization;

namespace MuseQuotaWidget.Models;

/// <summary>
/// 悬浮窗展示的一份额度快照。字段故意只保留“展示用”的数，不含任何账号凭证。
/// 唯一数据来源是 Muse 直连（内置登录后调 hatch-api），见 README。
/// </summary>
public sealed class QuotaData
{
    /// <summary>例如：免费版（无订阅）</summary>
    [JsonPropertyName("plan")]
    public string Plan { get; set; } = "免费版（无订阅）";

    /// <summary>周额度已用百分比，0-100</summary>
    [JsonPropertyName("usedPercent")]
    public double UsedPercent { get; set; }

    /// <summary>周额度剩余百分比，0-100；为空时由 100 - UsedPercent 推导</summary>
    [JsonPropertyName("remainingPercent")]
    public double? RemainingPercent { get; set; }

    public double Remaining => RemainingPercent ?? (100 - UsedPercent);

    /// <summary>周额度重置时间，含时区，例如 2026-10-29T11:31:00+08:00</summary>
    [JsonPropertyName("weeklyResetAt")]
    public DateTimeOffset? WeeklyResetAt { get; set; }

    /// <summary>额外 tokens 剩余量，展示用字符串，例如 31B</summary>
    [JsonPropertyName("additionalTokensLeft")]
    public string AdditionalTokensLeft { get; set; } = string.Empty;

    /// <summary>额外 tokens 已用百分比，0-100</summary>
    [JsonPropertyName("additionalTokensUsedPercent")]
    public double AdditionalTokensUsedPercent { get; set; }

    /// <summary>这份快照的更新时间，含时区</summary>
    [JsonPropertyName("updatedAt")]
    public DateTimeOffset? UpdatedAt { get; set; }
}
