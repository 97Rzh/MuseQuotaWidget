# MuseQuotaWidget — Muse 剩余额度悬浮窗

一个 Windows 桌面小悬浮窗：无边框、圆角、默认始终置顶，
鼠标拖动可移动，右键菜单可刷新 / 开关置顶 / 打开数据文件 / 退出。

显示内容：周额度剩余百分比、已用百分比、额外 tokens 剩余、
周额度重置时间及倒计时、数据更新时间。

## 实时链路（v2，不再手动改文件）

**Muse 没有给第三方桌面程序直接查询额度的公开接口**，
桌面 exe 自己是查不到你的额度的。唯一能查到的地方是 Muse agent 侧
的 `subscription-status` 通道，所以实时只能走这条链：

```
Muse agent 定时查额度 → 有变化才更新本仓库的 quota.json 并推送
    → 悬浮窗每 5 分钟从 GitHub 拉一次 quota.json
```

- 悬浮窗拉 GitHub 不耗 Muse 额度，只耗 GitHub API 调用次数。
- 更新端不做高频 agent 轮询：轻量脚本先查、只有百分比变了才
  触发推送，避免“监控本身把额度吃掉”。
- 悬浮窗底部会显示数据来源：GitHub 或本地文件。

要让悬浮窗走 GitHub 这路，需要在 exe 旁边放一个只读 token：

1. GitHub → Settings → Developer settings → Personal access tokens
   → Fine-grained tokens → New token；
2. 只勾这一个仓库 `97Rzh/MuseQuotaWidget`，权限只给 Contents
   的 Read（读 quota.json 够用），其他权限一律不给；
3. 把 token 存成 exe 旁边的 `github-token.txt`（纯文本、只有这一行）。
   这个文件已进 `.gitignore`，**绝不要提交进仓库、不要发给任何人**。
   没有这个文件时，悬浮窗自动回落到本地 `quota.json`。

## 当前数据（2026-10-22 16:38 查到）

- 计划：免费版（无订阅）
- 周额度：已用 7%，剩余 **93%**
- 重置：2026-10-29 11:31（CST）
- 额外 tokens：剩余 31B，已用 0%

## 在 Windows 上构建运行

需要 .NET 8 SDK（WPF 只能在 Windows 上编译，Linux 上编不了）：

```powershell
dotnet build -c Release
# 运行：
.\src\MuseQuotaWidget\bin\Release\net8.0-windows\MuseQuotaWidget.exe
```

也可以直接用 Visual Studio 打开 `MuseQuotaWidget.sln`，按 F5 运行。

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
  Models/QuotaData.cs                  # 额度快照模型
  Services/FileQuotaProvider.cs        # 读本地 quota.json，坏文件不崩
  Services/GitHubQuotaProvider.cs      # 从 GitHub 拉 quota.json（需本地 github-token.txt）
  quota.json                           # 额度数据（发布时会复制到 exe 旁边）
tools/update-quota.py                  # agent 端：查实时额度并更新 quota.json
```
