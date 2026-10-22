using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MuseQuotaWidget.Services;

/// <summary>
/// Muse 额度直连：实现思路参照 HuiAnnn/ai-quota 的 Muse 部分，
/// 但用 WPF + WebView2 重写（ai-quota 是 macOS Swift + WKWebView）。
/// 关键约定（与 ai-quota 一致，改动处另有注释说明）：
/// - 登录在应用自己的 WebView2 数据文件夹里完成，不用系统浏览器、
///   不用 Muse 原生应用的登录状态；
/// - 令牌只存在内存里，绝不写盘、绝不进日志；
/// - 令牌只发给 hatch-api.meta.ai 这一个主机，不带 Cookie；
/// - 额度快照里只有百分比、时间和词元余额，不含任何凭据。
/// </summary>
public enum MuseAuthKind
{
    LoginRequired,
    AccessRestricted,
    CheckpointRequired,
    TokenUnavailable,
    InvalidResponse,
    NetworkUnavailable,
    QuotaAccessRejected,
    RateLimited,
    AccountChanged,
    RequestRejected,
}

public sealed class MuseAuthException : Exception
{
    public MuseAuthKind Kind { get; }
    public int? StatusCode { get; }

    public MuseAuthException(MuseAuthKind kind, int? statusCode = null)
        : base(kind.ToString())
    {
        Kind = kind;
        StatusCode = statusCode;
    }

    public string MessageZh => Kind switch
    {
        MuseAuthKind.LoginRequired => "尚未完成 Muse 网页登录（或会话已失效）。请在登录窗口登录后重试。",
        MuseAuthKind.AccessRestricted => "Muse 账号尚未获得访问权限。请在登录窗口完成访问流程。",
        MuseAuthKind.CheckpointRequired => "Muse 需要验证账号。请在登录窗口完成验证后重试。",
        MuseAuthKind.TokenUnavailable => "网页登录已通过，但 Muse 未提供额度访问令牌；此会话的额度读取尚未完成。",
        MuseAuthKind.InvalidResponse => "Muse 返回了当前版本无法识别的数据。",
        MuseAuthKind.NetworkUnavailable => "网络请求失败或超时。请稍后重试。",
        MuseAuthKind.QuotaAccessRejected => "Muse 额度接口拒绝了当前网页凭据；尚未确认网页令牌可访问额度。",
        MuseAuthKind.RateLimited => "Muse 暂时限制了请求频率。请稍后重试。",
        MuseAuthKind.AccountChanged => "账号或会话已切换，请重试。",
        MuseAuthKind.RequestRejected => StatusCode is { } code
            ? $"Muse 返回 HTTP {code}，请稍后重试。"
            : "Muse 返回了无法识别的错误，请稍后重试。",
        _ => "未知错误。",
    };
}

/// <summary>仅存内存的凭据。Token 与指纹成对出现，指纹变了就视为换号。</summary>
public sealed class MuseCredential
{
    public string Token { get; }
    public string Fingerprint { get; }

    public MuseCredential(string token, string fingerprint)
    {
        Token = token;
        Fingerprint = fingerprint;
    }

    /// 与 ai-quota 一致：SHA256(viewer_id + '\0' + session_binding_id) 的十六进制小写。
    public static string FingerprintFor(string viewerId, string? bindingId)
    {
        var bytes = Encoding.UTF8.GetBytes(viewerId + "\0" + (bindingId ?? string.Empty));
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }
}

public static class MuseApiDecoder
{
    /// 解析 hatch-api 的订阅响应，同时兼容它可能返回的蛇形字段
    /// （percent_used / resets_at / topup_balance 等，见 ai-quota 的解码器）
    /// 与网页端 RSC 里的驼峰字段（percentUsed / resetsAt）。
    public static Models.QuotaData ParseQuota(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        // usage 优先在顶层找；若 hatch-api 实际把它包了一层
        // （subscription / data / result），也接受，不直接判无法识别。
        var container = root;
        if ((!TryGet(root, "usage", out var usage) || usage.ValueKind != JsonValueKind.Object)
            && !FindNestedUsage(root, out usage, out container))
        {
            throw new MuseAuthException(MuseAuthKind.InvalidResponse);
        }

        var state = TryGetString(usage, "state") ?? string.Empty;
        var percentUsed = TryGetNumber(usage, "percent_used", "percentUsed");
        if (percentUsed is null)
        {
            throw new MuseAuthException(MuseAuthKind.InvalidResponse);
        }

        var data = new Models.QuotaData
        {
            Plan = "Muse",
            UsedPercent = percentUsed.Value,
            RemainingPercent = Math.Clamp(100 - percentUsed.Value, 0, 100),
            WeeklyResetAt = ParseReset(usage),
            AdditionalTokensUsedPercent = 0,
            AdditionalTokensLeft = string.Empty,
            UpdatedAt = DateTimeOffset.Now,
        };
        _ = state; // state 目前只用于区分：METERED 之外仍按已用百分比展示，不虚构。

        // topup 字段也可能跟 usage 一起被包在内层对象里。
        var topupBalance = TryGetNumber(root, "topup_balance", "topupBalance")
            ?? TryGetNumber(container, "topup_balance", "topupBalance");
        var topupTotal = TryGetNumber(root, "topup_total", "topupTotal")
            ?? TryGetNumber(container, "topup_total", "topupTotal");
        if (topupBalance is { } balance)
        {
            data.AdditionalTokensLeft = FormatTokens(balance);
            if (topupTotal is { } total && total > 0)
            {
                data.AdditionalTokensUsedPercent = Math.Clamp(100 * (1 - balance / total), 0, 100);
            }
        }

        var label = TryGetString(root, "usage_row_label", "usageRowLabel")
            ?? TryGetString(container, "usage_row_label", "usageRowLabel");
        if (!string.IsNullOrWhiteSpace(label))
        {
            // usage_row_label 在中文界面下就是“免费版”一类的展示名，优先用它。
            data.Plan = label;
        }

        return data;
    }

    private static bool FindNestedUsage(JsonElement root, out JsonElement usage, out JsonElement container)
    {
        usage = default;
        container = root;
        foreach (var wrapper in new[] { "subscription", "data", "result" })
        {
            if (TryGet(root, wrapper, out var inner) && inner.ValueKind == JsonValueKind.Object
                && TryGet(inner, "usage", out var nested) && nested.ValueKind == JsonValueKind.Object)
            {
                usage = nested;
                container = inner;
                return true;
            }
        }

        return false;
    }

    private static string FormatTokens(double balance)
    {
        // 只做数值格式化，不做单位换算猜测：1.24e9 就是“12.4亿词元”，
        // 不把它硬说成 31B（那个 31B 是 subscription-status 的另一种口径）。
        if (balance >= 100_000_000)
        {
            return $"{balance / 100_000_000:0.#}亿词元";
        }

        return $"{balance:0}词元";
    }

    private static DateTimeOffset? ParseReset(JsonElement usage)
    {
        // 字符串：ai-quota 只认带日期或带时区偏移的 ISO 格式，照搬。
        if (TryGetString(usage, "resets_at", "resetsAt") is { } raw && !string.IsNullOrWhiteSpace(raw))
        {
            if (DateTimeOffset.TryParse(raw, out var parsed))
            {
                return parsed;
            }

            if (DateTime.TryParseExact(raw, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal, out var day))
            {
                // 只有日期、没有时刻时，只精确到天，显示为当天零点（UTC）。
                return new DateTimeOffset(day, TimeSpan.Zero);
            }

            return null;
        }

        // 数字：与 ai-quota 不同，这里做了转换，因为已用实测验证过——
        // 网页端 RSC 里的 resetsAt=1793244675（秒）换算后正好是
        // 2026-10-29 11:31 CST，与 subscription-status 的重置时间完全对上，
        // 所以秒级 Unix 时间戳的单位是确定的，不是猜测。
        if (TryGetNumber(usage, "resets_at", "resetsAt") is { } num)
        {
            try
            {
                return num >= 100_000_000_000
                    ? DateTimeOffset.FromUnixTimeMilliseconds((long)num)
                    : DateTimeOffset.FromUnixTimeSeconds((long)num);
            }
            catch
            {
                return null;
            }
        }

        return null;
    }

    private static bool TryGet(JsonElement obj, string name, out JsonElement value)
    {
        if (obj.ValueKind == JsonValueKind.Object && obj.TryGetProperty(name, out value))
        {
            return true;
        }

        value = default;
        return false;
    }

    private static string? TryGetString(JsonElement obj, params string[] names)
    {
        foreach (var name in names)
        {
            if (TryGet(obj, name, out var value) && value.ValueKind == JsonValueKind.String)
            {
                return value.GetString();
            }
        }

        return null;
    }

    private static double? TryGetNumber(JsonElement obj, params string[] names)
    {
        foreach (var name in names)
        {
            if (!TryGet(obj, name, out var value))
            {
                continue;
            }

            // 数字直接取；字符串形式的数字（例如 "8"）也接受，
            // 避免只因类型不同就判无法识别。
            if (value.ValueKind == JsonValueKind.Number
                && value.TryGetDouble(out var num) && double.IsFinite(num) && num >= 0)
            {
                return num;
            }

            if (value.ValueKind == JsonValueKind.String
                && double.TryParse(value.GetString(),
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out var parsed)
                && double.IsFinite(parsed) && parsed >= 0)
            {
                return parsed;
            }
        }

        return null;
    }
}
