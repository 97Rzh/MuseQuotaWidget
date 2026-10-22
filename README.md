# MuseQuotaWidget — Muse 剩余额度悬浮窗

一个 Windows 桌面小悬浮窗：无边框、圆角、默认始终置顶，
鼠标拖动可移动，右键菜单可刷新 / 开关置顶 / 打开数据文件 / 退出。

显示内容：周额度剩余百分比、已用百分比、额外 tokens 剩余、
周额度重置时间及倒计时、数据更新时间。

## 实时链路（v3，内置登录直连，参照 ai-quota）

本项目 v3 的 Muse 直连实现，思路参照
[HuiAnnn/ai-quota](https://github.com/HuiAnnn/ai-quota) 里 Muse
那部分（macOS Swift + WKWebView），用 WPF + WebView2 重写，
Swift 代码没有直接复制，逻辑按 ai-quota 的做法对齐：

```
悬浮窗右键“登录 Muse…” → 内置 WebView2 登录窗口打开 muse.ai
  → 用户在窗口里登录 → 点“验证登录并读取额度”
  → 窗口内同源 POST /api/auth/check 换一个访问令牌（只取
    outcome / access_token / viewer_id / session_binding_id 等字段）
  → 悬浮窗用该令牌 GET https://hatch-api.meta.ai/hatch/subscription
    （Authorization: Bearer 令牌，X-API-Version: 1.0.0，不带 Cookie，
    不请求 include=agreement，不碰支付与协议详情）
  → 每 5 分钟用同一令牌刷新一次，直到令牌失效
```

- 登录在应用自己的 WebView2 数据文件夹
 （`%LOCALAPPDATA%\MuseQuotaWidget\WebView2`）里完成，不用系统
  浏览器、不用 Muse 原生应用的登录状态；Cookie 持久化在该文件夹，
  下次打开登录窗口时若会话未过期可直接验证。
- **令牌只存在内存里**，绝不写盘、绝不进日志、绝不进 quota.json、
  绝不发给除 hatch-api 之外的任何主机；令牌与账号指纹
  （SHA256(viewer_id + session_binding_id)）成对核对，指纹变了
  就视为换号并丢弃令牌。
- 读额度接口本身不是对话，不产生对话 token；悬浮窗底部会显示
  数据来源：Muse 直连 / GitHub / 本地文件。
- 数据源优先级：Muse 直连 > GitHub 快照 > 本地 quota.json。
  直连失败（网络、限流）时不丢令牌，临时回落并在下次刷新重试；
  登录失效或换号时清令牌并提示重新登录。

GitHub 回落路（直连不可用时用），需要在 exe 旁边放一个只读 token：

1. GitHub → Settings → Developer settings → Personal access tokens
   → Fine-grained tokens → New token；
2. 只勾这一个仓库 `97Rzh/MuseQuotaWidget`，权限只给 Contents
   的 Read（读 quota.json 够用），其他权限一律不给；
3. 把 token 存成 exe 旁边的 `github-token.txt`（纯文本、只有这一行）。
   这个文件已进 `.gitignore`，**绝不要提交进仓库、不要发给任何人**。
   没有这个文件时，悬浮窗自动回落到本地 `quota.json`。

## 当前数据（2026-10-22 17:04 查到，本地回落快照）

- 计划：免费版（无订阅）
- 周额度：已用 8%，剩余 **92%**
- 重置：2026-10-29 11:31（CST）
- 额外 tokens：剩余 31B，已用 0%

## 在 Windows 上构建运行

需要 .NET 8 SDK（WPF 只能在 Windows 上编译，Linux 上编不了）
和 WebView2 Runtime（Windows 11 自带 Edge 的机器上一般已有，
没有时需先装 Evergreen Runtime）：

```powershell
dotnet build -c Release
# 首次构建需要联网还原 Microsoft.Web.WebView2 的 NuGet 包
# 运行：
.\src\MuseQuotaWidget\bin\Release\net8.0-windows\MuseQuotaWidget.exe
```

也可以直接用 Visual Studio 打开 `MuseQuotaWidget.sln`，按 F5 运行。

首次使用：右键悬浮窗 → “登录 Muse…” → 在内置窗口里登录
muse.ai → 点“验证登录并读取额度”。只有在真实额度响应通过
解码后窗口才会关闭并显示额度；失败时窗口保持打开，可重试。
右键“退出登录”只清内存里的令牌，网页登录 Cookie 仍在
WebView2 数据文件夹中（下次登录无需重新输入密码）；
彻底退出请手动删除该文件夹。

**本机未验证项（Linux 编不了 WPF、也测不了 WebView2 登录）：**
hatch-api 返回的 `resets_at` 格式需在 Windows 上第一次登录后
实测确认——代码已同时兼容字符串日期/ISO 时间和数字 Unix 时间戳
（数字秒级已用网页端数据验证过：1793244675 正好是
2026-10-29 11:31 CST），若 hatch-api 的字段名或格式有出入，
以第一次登录后的实际返回为准调整解码器。

## 手动更新（备用，不走 GitHub 时用）

右键悬浮窗 → “打开数据文件 (quota.json)”，改
`usedPercent` / `remainingPercent` / `weeklyResetAt` /
`additionalTokensLeft` / `updatedAt`，保存后右键“刷新数据”
立即刷新。`quota.json` 里只有展示用的百分比和时间，
**不要往里面写任何账号、密码、token 或 API Key**。

Agent 端的更新脚本在 `tools/update-quota.py`：只在 Muse agent
所在的机器上运行（依赖 `subscription-status`），它只更新文件、
不推送，推送由“有变化才触发”的那一步做。

## 开机自启（可选）

把 Release 下 `MuseQuotaWidget.exe` 的快捷方式放进启动文件夹：

```
Win + R → shell:startup → 把快捷方式粘贴进去
```

## 文件结构

```
MuseQuotaWidget.sln
src/MuseQuotaWidget/
  MuseQuotaWidget.csproj   # .NET 8 + WPF
  App.xaml / App.xaml.cs
  MainWindow.xaml / MainWindow.xaml.cs  # 悬浮窗界面与刷新、倒计时逻辑
  Models/QuotaData.cs                  # 额度快照模型（只有百分比/时间/余额，无凭据）
  Services/FileQuotaProvider.cs        # 读本地 quota.json，坏文件不崩
  Services/GitHubQuotaProvider.cs      # 从 GitHub 拉 quota.json（需本地 github-token.txt）
  Services/MuseApi.cs                  # hatch-api 响应解码 + 令牌指纹（参照 ai-quota）
  Services/MuseSession.cs              # 内存会话 + hatch-api 直连（令牌不存盘）
  LoginWindow.xaml / LoginWindow.xaml.cs  # 内置 WebView2 登录窗口 + /api/auth/check
  quota.json                           # 额度数据（发布时会复制到 exe 旁边）
tools/update-quota.py                  # agent 端：查实时额度并更新 quota.json
```
