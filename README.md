# MuseQuotaWidget — Muse 剩余额度悬浮窗

一个 Windows 桌面小悬浮窗：无边框、圆角、默认始终置顶，
鼠标拖动可移动，右键菜单可刷新 / 登录 / 退出登录 /
设置刷新频率 / 开关置顶 / 退出。

**唯一数据来源是 Muse 直连（内置登录），没有 GitHub 快照、
没有本地数据文件、没有手动填数。**未登录时只显示“未登录”，
不拿旧数据冒充新数据；刷新失败时继续显示内存里
的上次成功快照，时间行只写短提示。

界面极简：悬浮窗上只显示一个周额度剩余百分比和一条进度条
（低于 50% 变黄、低于 20% 变红，条的颜色跟百分比一致），
下面一行只放刷新时间（每周额度重置时间），不带任何前缀字样。
不显示标题、计划、已用、额外词元等任何字样。
刷新时间一律转本地时间显示：hatch-api 返回的 Unix / ISO
时间本身是 UTC（例如 1793244675 秒 = UTC 03:31），
解码时转本地后才是 11:31，不再原样显示 UTC。

## 刷新频率设置

右键悬浮窗 → “设置刷新频率…”，拖动滑块选 1-60 分钟，
点“确定”立即生效并保存到
`%LOCALAPPDATA%\MuseQuotaWidget\settings.json`（只存分钟数，
不存账号与令牌），下次启动沿用；点“取消”不改。
默认 5 分钟。刷新是读额度接口，不是对话，不耗对话 token；
过于频繁可能触发限流，建议 5 分钟以上。

## 额外词元（已不再显示，仅作对数记录）

极简版悬浮窗不再显示额外词元。之前显示 12.4 亿时算术本身
没错：hatch-api 返回的 topup_balance 就是 1,240,000,000，
÷ 1 亿 = 12.4 亿；而 agent 侧的 `subscription-status` 一直说
额外 tokens 是 31B、0% 已用，两边不是同一个数，至少有一个
字段不是同一口径。**这里不硬乘一个 2.5 或 25 的系数去凑
31 亿，那是造数据。**

对数方法仍在：每次成功刷新都会在诊断日志里记一行
`quota numbers:`，把 hatch-api 返回体里的数值字段原样列出来
（不记令牌与账号 id）。右键悬浮窗 → “打开诊断日志”，
找到最新的一行 `quota numbers:`，看里面到底有没有一个
3,100,000,000（31 亿）或 31,000,000,000（31B）的字段，
以及它叫什么名字；到时按日志里的实际字段名再定。

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
- **令牌只存在内存里**，绝不写盘、绝不进日志、
  绝不发给除 hatch-api 之外的任何主机；令牌与账号指纹
  （SHA256(viewer_id + session_binding_id)）成对核对，指纹变了
  就视为换号并丢弃令牌。
- 读额度接口本身不是对话，不产生对话 token。
- 直连失败（网络、限流）时不丢令牌，下次定时刷新再试；
  登录失效或换号时清令牌并提示重新登录。

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
WebView2 数据文件夹中；彻底退出请手动删除该文件夹。

**之后每次打开软件不用再点登录：**启动时悬浮窗会在后台
自动登录——用上次登录留下的 Cookie，在一个离屏隐藏的
后台窗口里加载 muse.ai 并静默换令牌，成功就直接显示额度，
用户看不到这个窗口、不用点任何东西。令牌本身仍只存内存，
重启后令牌丢了也不要紧，后台登录会用 Cookie 再换一个。
只有 Cookie 已过期、被清除或 Muse 要求重新验证时，
后台登录才会失败，那时悬浮窗显示“未登录”，右键手动登录一次
即可；手动点“刷新数据”时若令牌已丢，也会先试一次后台登录。

**本机未验证项（Linux 编不了 WPF、也测不了 WebView2 登录）：**
hatch-api 返回的 `resets_at` 格式需在 Windows 上第一次登录后
实测确认——代码已同时兼容字符串日期/ISO 时间和数字 Unix 时间戳
（数字秒级已用网页端数据验证过：1793244675 正好是
2026-10-29 11:31 CST），若 hatch-api 的字段名或格式有出入，
以第一次登录后的实际返回为准调整解码器。

**验证失败时怎么定位：**登录窗口的提示现在会写明是“登录检查”
还是“额度读取”那一步失败，并把结构记录写到本地诊断日志
`%LOCALAPPDATA%\MuseQuotaWidget\muse-debug.log`（右键悬浮窗 →
“打开诊断日志”）。日志里只有字段名、字段类型、HTTP 状态、
outcome / type / reason / state 这类状态词，**没有令牌、
没有账号 id、没有百分比与余额**，可以放心发出来；发的时候
先看最后一行是 `auth:` 还是 `quota invalid:`，就知道是哪一步
的返回体结构对不上。

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
  Services/MuseApi.cs                  # hatch-api 响应解码 + 令牌指纹（参照 ai-quota）
  Services/MuseSession.cs              # 内存会话 + hatch-api 直连（令牌不存盘）
  Services/MuseDiagnostics.cs          # 本地诊断日志（不记令牌与账号 id）
  Services/SettingsStore.cs            # 刷新频率本地设置（只存分钟数）
  LoginWindow.xaml / LoginWindow.xaml.cs  # 内置 WebView2 登录窗口 + /api/auth/check
  SettingsWindow.xaml / SettingsWindow.xaml.cs  # 刷新频率滑块设置窗
```
