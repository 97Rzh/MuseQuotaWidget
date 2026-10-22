# MuseQuotaWidget — Muse 剩余额度悬浮窗

一个 Windows 桌面小悬浮窗：无边框、圆角、默认始终置顶，
鼠标拖动可移动，右键菜单可刷新 / 开关置顶 / 打开数据文件 / 退出。

显示内容：周额度剩余百分比、已用百分比、额外 tokens 剩余、
周额度重置时间及倒计时、数据更新时间。

## 当前初始数据（2026-10-22 查到）

- 计划：免费版（无订阅）
- 周额度：已用 6%，剩余 **94%**
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

## 更新额度数据（重要）

**Muse 目前没有给第三方桌面程序直接查询额度的公开接口**，
所以这个悬浮窗 v1 不会、也不应假装能自动联网查到你的账号额度。
它的数据来源是程序目录下的 `quota.json`：

1. 问 Muse 一句“我的剩余额度是多少”，拿到最新数字；
2. 右键悬浮窗 → “打开数据文件 (quota.json)”；
3. 改 `usedPercent` / `remainingPercent` / `weeklyResetAt` /
   `additionalTokensLeft` / `updatedAt`，保存；
4. 悬浮窗每 5 分钟自动重读，也可右键“刷新数据”立即刷新。

`quota.json` 里只有展示用的百分比和时间，**不要往里面写任何账号、
密码、token 或 API Key**。

以后如果 Muse 出了可供桌面程序调用的额度接口，只需新增一个
数据源实现替换掉 `Services/FileQuotaProvider.cs`，界面不用动。

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
  Services/FileQuotaProvider.cs        # 读 quota.json，坏文件不崩
  quota.json                           # 额度数据（发布时会复制到 exe 旁边）
```
