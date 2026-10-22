using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using MuseQuotaWidget.Models;

namespace MuseQuotaWidget.Services;

/// <summary>
/// 从 GitHub 仓库拉取 quota.json（agent 定时更新的那份）。
/// 私有仓库必须带 token：token 只放在 exe 旁边的 github-token.txt 里，
/// 这个文件已进 .gitignore，绝不会随代码提交；没有 token 文件时直接
/// 返回“未尝试”，调用方回落到本地 quota.json。
/// 悬浮窗这边拉 GitHub 不耗 Muse 额度，耗的只是 GitHub API 调用次数
/// （带 token 每小时 5000 次，5 分钟拉一次远远够用）。
/// </summary>
public sealed class GitHubQuotaProvider
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(10) };

    private const string Url =
        "https://api.github.com/repos/97Rzh/MuseQuotaWidget/contents/src/MuseQuotaWidget/quota.json?ref=master";

    /// <returns>
    /// Data：拉到的快照，失败为 null。
    /// TokenPresent：exe 旁边有没有放 github-token.txt。
    /// </returns>
    public async Task<(QuotaData? Data, bool TokenPresent)> TryLoadAsync()
    {
        var tokenPath = Path.Combine(AppContext.BaseDirectory, "github-token.txt");
        if (!File.Exists(tokenPath))
        {
            return (null, false);
        }

        var token = (await File.ReadAllTextAsync(tokenPath)).Trim();
        if (string.IsNullOrEmpty(token))
        {
            return (null, false);
        }

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, Url);
            request.Headers.UserAgent.ParseAdd("MuseQuotaWidget/1.0");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            request.Headers.Accept.ParseAdd("application/vnd.github+json");
            using var response = await Http.SendAsync(request);
            if (!response.IsSuccessStatusCode)
            {
                return (null, true);
            }

            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            if (!doc.RootElement.TryGetProperty("content", out var contentProp))
            {
                return (null, true);
            }

            var base64 = contentProp.GetString()?
                .Replace("\n", string.Empty)
                .Replace("\r", string.Empty)
                .Replace(" ", string.Empty);
            if (string.IsNullOrEmpty(base64))
            {
                return (null, true);
            }

            var json = Encoding.UTF8.GetString(Convert.FromBase64String(base64));
            var data = JsonSerializer.Deserialize<QuotaData>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            });
            return (data, true);
        }
        catch
        {
            // 网络失败、解析失败都只算“这次拉不到”，调用方用本地数据顶上。
            return (null, true);
        }
    }
}
