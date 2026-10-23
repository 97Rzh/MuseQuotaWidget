# MuseQuotaWidget — Muse 剩余额度悬浮窗（Python 版，Mac / Windows 通用）

一个桌面小悬浮窗：无边框、圆角、默认始终置顶，
鼠标拖动可移动（点到按钮、滑块时不拖动）。没有右键菜单：
鼠标悬停到悬浮窗上时右上角出现一个齿轮按钮，点它展开
内置设置面板；点齿轮或面板里的“完成”可收起。

边缘隐藏：窗体永远拖不出屏幕，拖动全程按所有屏的虚拟外框钳制，
且至少交叠一屏，双屏之间可以自由拖过去；屏间交界不算边，
拖过交界不会触发吸入 / 隐藏，只有拖到某屏真正的上 / 下 /
最左 / 最右外边才会触发；拖到边缘松手就自动隐藏，不用双击，
变成贴在边上的一条 96x48 小条，条里只显示剩余额度
（颜色跟主窗一致）；鼠标划过小条，窗体在边上完整展开，
鼠标离开完整窗体，又变回小条；把展开后的窗体拖离边缘，
就取消隐藏、恢复成普通悬浮窗。设置面板展开时不触发隐藏，
点齿轮展开设置会先取消隐藏。

边缘灵魂抽取动画：拖动完整窗体靠近某条边（180px 内）时，
那条边上出现一条灵魂带：从窗体边伸向边口的半透明发光带，
带宽是窗体沿边尺寸的 60%，窗体边亮、边口处淡出，
带子里有光点带着淡尾从窗体边漂向边口、越近边口越淡；
窗体不再被轻吸，窗体跟鼠标走，灵魂带自己从窗体边流向边口。
松手贴边后不再瞬间切小条，而是 600ms 形变过渡：窗体
滑向边、缩小、透明度先跌到 0.2 再亮回 1.0，中途在最暗处
换成小条内容，最后定在小条上。灵魂带不抢鼠标、不抢焦点，
只在拖动时出现，松手、拖离、展开设置时都消失。

## 打包成 Mac 程序（.app）

图标在 `assets/` 里：深色圆角方块 + 绿色圆环 + 白色 %，
跟悬浮窗本体一个风格，不绑定具体额度数值。
`assets/make_icon.py` 是画图标的脚本（只依赖 Pillow），
改完设计后跑它就能重新生成 `icon.png` / `icon.iconset/` / `icon.ico`。

在 Mac 上打包（必须在 Mac 上跑，Linux 上打出来不是 .app）：

```zsh
cd ~/Desktop/MuseQuotaWidget
./build_mac.sh
```

这一步会先装依赖和 PyInstaller，再用 macOS 自带的
`iconutil` 把 `assets/icon.iconset/` 转成 `assets/icon.icns`，
最后用 PyInstaller `--windowed` 打出 `dist/MuseQuotaWidget.app`，
可直接拖到“应用程序”里双击打开，不用再走终端。

注意：打出来的 .app 没有签名，第一次打开会被 Gatekeeper 拦，
右键点 .app → “打开” → 再点“打开”，或者跑
`xattr -cr dist/MuseQuotaWidget.app` 后再双击。
设置、日志、浏览器 Cookie 还是存在
`~/Library/Application Support/MuseQuotaWidget/`，跟终端版同一套，
所以 .app 版不用重新登录（前提是终端版已经登录过、Cookie 还没过期）。
如果登录窗在 .app 里报 WebEngine 不可用，先确认打包时装的是
最新版 PyInstaller（PyInstaller 6.5 起已在 Mac 上关掉 QtWebEngine
沙箱，避免 QtWebEngineProcess 崩溃），再把报错贴出来。

## 打包成 Windows 程序（.exe）

Windows 版用 `build_windows.bat`，不用 `iconutil` / `.icns`，
图标直接用已有的 `assets\icon.ico`。在 Windows 上跑（双击
文件资源管理器里的 `build_windows.bat` 也行，脚本会自动切到
自己所在的目录）：

```powershell
cd E:\Project\MuseQuotaWidget
.\build_windows.bat
```

这一步会先装依赖和 PyInstaller，再用 PyInstaller `--windowed`
打出 `dist\MuseQuotaWidget\MuseQuotaWidget.exe`。跟 Mac 一样
不用 `--onefile`：QtWebEngine 的子进程要跟 exe 放在一起，
`dist\MuseQuotaWidget\` 整个文件夹就是程序，exe 不能单独拷走。
打出来的 exe 没有签名，第一次打开 Windows 可能会弹 SmartScreen，
点“更多信息”再点“仍要运行”就行。设置、日志、浏览器 Cookie
还是存在 `%LOCALAPPDATA%\MuseQuotaWidget\`，跟终端版同一套。

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

## 运行（Mac / Windows）

需要 Python 3.10+ 和 PySide6 + PySide6-WebEngine
（Qt 悬浮窗 + QtWebEngine 登录窗，两个包都要装，见 requirements.txt）。
C# / WPF 版已整段删除，git 历史（5337ffe 及之前）里还能找回，
不要再用 Visual Studio / dotnet 构建。

```bash
# 第一次：装依赖（Mac 用 python3，Windows 用 python）
python3 -m pip install -r requirements.txt

# 启动
python3 main.py
# Mac 也可以：./run.sh
# Windows 也可以：双击 run.bat
```

**本机未验证项（Linux 编不了 GUI、也测不了 QtWebEngine 登录）：**
悬浮窗的圆角、透明、齿轮悬停、拖动、设置面板展开后的
528 宽与高度自适应，以及 QtWebEngine 登录 / 后台自动登录，
都需要在 Mac 和 Windows 上第一次运行时实测确认。
Linux 上只做了核心逻辑单测（额度解码、节奏计算、登录指纹），
没有跑过界面。

首次使用：点齿轮 → “登录 Muse…” → 在内置浏览器窗口里登录
muse.ai → 点“验证登录并读取额度”。只有在真实额度响应通过
解码后窗口才会关闭并显示额度；失败时窗口保持打开，可重试。
点齿轮 → “退出登录”只清内存里的令牌，网页登录 Cookie 仍在
浏览器数据文件夹中；彻底退出请手动删除该文件夹
（Mac：`~/Library/Application Support/MuseQuotaWidget/QtWebEngine`，
Windows：`%LOCALAPPDATA%\MuseQuotaWidget\QtWebEngine`）。

**之后每次打开软件不用再点登录：**启动时悬浮窗会在后台
自动登录——用上次登录留下的 Cookie，在一个移到屏幕外的
后台浏览器窗口里加载 muse.ai 并静默换令牌，成功就直接显示额度，
用户看不到这个窗口、不用点任何东西。令牌本身仍只存内存，
重启后令牌丢了也不要紧，后台登录会用 Cookie 再换一个。
只有 Cookie 已过期、被清除或 Muse 要求重新验证时，
后台登录才会失败，那时悬浮窗显示“未登录”，点齿轮 → 登录一次
即可；面板里点“刷新数据”时若令牌已丢，也会先试一次后台登录。

如果登录窗报 QtWebEngine 不可用：不要只重装 PySide6，
PySide6 6.12 起已拆包，基础包不含 WebEngine，要单独装
（`python3 -m pip install PySide6-WebEngine`，Mac 上那个轮子
约 250MB，装的时候要等一会儿），装完重启悬浮窗再登录。
主悬浮窗仍能打开、只显示“未登录”，额度要等登录可用后才能读取。

## 设置面板（齿轮按钮，RamanVista 风格）

鼠标悬停到悬浮窗上时右上角出现齿轮按钮（平时不显示），
点它：额度区缩到左上角（大字 44 → 28，居中 → 左对齐），
窗体从 240 宽放大到 528 宽，右侧出现设置面板；再点齿轮
或面板底部的“完成”就收回 240 宽。面板控件风格参考
RamanVista：深色表面 #2B2D33 / #25272D、边框 #606060、
主色浅蓝 #4FC3F7、卡片圆角 12、按钮圆角 6、滑块拇指
#4FC3F7（不引 MaterialDesign 包，只复刻颜色与样式）。

面板里就是原来右键菜单的全部内容，重新排成卡片：
账号（登录状态 + “登录 Muse…” / “退出登录”，已登录时
登录按钮禁用）、数据（“刷新数据”）、刷新频率（滑块
1-60 分钟，拖动立即生效并保存到设置文件，只存分钟数，
不存账号与令牌，下次启动沿用；默认 5 分钟）、显示
（“始终置顶”复选框）、其他（“打开诊断日志”）、
退出软件。刷新是读额度接口，不是对话，不耗对话 token；
过于频繁可能触发限流，建议 5 分钟以上。

设置与日志文件位置：
- Mac：`~/Library/Application Support/MuseQuotaWidget/settings.json`
  与 `muse-debug.log`
- Windows：`%LOCALAPPDATA%\MuseQuotaWidget\settings.json`
  与 `muse-debug.log`

## 用量节奏（第二版，主条下方）

主条下方有一条用量节奏控件，只回答“比平均快还是慢”，
不重复显示已用%：一条绿→黄→红渐变刻度，中央白线是平均线，
白点是你的实际偏差，偏左慢、偏右快，下方写“慢 / 平均 / 快”
和一行“快/慢 · 预计用完”。窗口高度随内容自适应，
有节奏控件时比只有百分比时高，重置时间拿不到时节奏控件
隐藏，只剩百分比、主条与时间。

算法：周期按 7 天计，起点 = 重置时间 - 7 天；
平均应为 = 已过天数 / 7 × 100%；
差值 Δ = 已用% - 平均应为%（已用% = 100 - 剩余%）。
颜色只看 Δ（百分点，不用比值，避免周期初期比值爆炸）：
Δ ≤ -5 绿、-5 ~ +5 黄持平、+5 ~ +20 橙、≥ +20 深红；
白点位置把 Δ 钳制到 [-25, +25] 再映射到刻度左到右，
中央 = Δ 0。预计用完按当前速度（已用 / 已过天数）外推：
预计用完在重置前写“预计提前 X 天用完”，在重置后写
“预计重置时还剩 X%”，正好在重置时写“预计正好在重置时用完”；
预计是外推不是承诺，速度一变它就变；已过天数为 0 时
算不出速度，只写快/慢。

## 额外词元（已不再显示，仅作对数记录）

悬浮窗不再显示额外词元。之前 C# 版显示 12.4 亿时算术本身
没错：hatch-api 返回的 topup_balance 就是 1,240,000,000，
÷ 1 亿 = 12.4 亿；而 agent 侧的 `subscription-status` 一直说
额外 tokens 是 31B、0% 已用，两边不是同一个数，至少有一个
字段不是同一口径。**这里不硬乘一个 2.5 或 25 的系数去凑
31 亿，那是造数据。**

对数方法仍在：每次成功刷新都会在诊断日志里记一行
`quota numbers:`，把 hatch-api 返回体里的数值字段原样列出来
（不记令牌与账号 id）。点齿轮 → “打开诊断日志”，
找到最新的一行 `quota numbers:`，看里面到底有没有一个
3,100,000,000（31 亿）或 31,000,000,000（31B）的字段，
以及它叫什么名字；到时按日志里的实际字段名再定。

## 实时链路（内置登录直连，参照 ai-quota）

思路参照 [HuiAnnn/ai-quota](https://github.com/HuiAnnn/ai-quota) 里 Muse
那部分（macOS Swift + WKWebView），Python 版用 QtWebEngine 重写，
Swift 代码没有直接复制，逻辑按 ai-quota 的做法对齐：

```
点齿轮 → “登录 Muse…” → 内置 QtWebEngine 窗口打开 muse.ai
  → 用户在窗口里登录 → 点“验证登录并读取额度”
  → 窗口内同源 POST /api/auth/check 换一个访问令牌（只取
    outcome / access_token / viewer_id / session_binding_id 等字段）
  → 悬浮窗用该令牌 GET https://hatch-api.meta.ai/hatch/subscription
    （Authorization: Bearer 令牌，X-API-Version: 1.0.0，不带 Cookie，
    不请求 include=agreement，不碰支付与协议详情）
  → 每 5 分钟用同一令牌刷新一次，直到令牌失效
```

- 登录在应用自己的浏览器数据文件夹里完成，不用系统
  浏览器、不用 Muse 原生应用的登录状态；Cookie 持久化在该文件夹，
  下次打开登录窗口时若会话未过期可直接验证。
- **令牌只存在内存里**，绝不写盘、绝不进日志、
  绝不发给除 hatch-api 之外的任何主机；令牌与账号指纹
  （SHA256(viewer_id + session_binding_id)）成对核对，指纹变了
  就视为换号并丢弃令牌。
- 读额度接口本身不是对话，不产生对话 token。
- 直连失败（网络、限流）时不丢令牌，下次定时刷新再试；
  登录失效或换号时清令牌并提示重新登录。

**验证失败时怎么定位：**登录窗口的提示现在会写明是“登录检查”
还是“额度读取”那一步失败，并把结构记录写到本地诊断日志
（点齿轮 → “打开诊断日志”）。日志里只有字段名、字段类型、HTTP 状态、
outcome / type / reason / state 这类状态词，**没有令牌、
没有账号 id、没有百分比与余额**，可以放心发出来；发的时候
先看最后一行是 `auth:` 还是 `quota invalid:`，就知道是哪一步
的返回体结构对不上。

## 文件结构

```
main.py                  # 入口
requirements.txt         # PySide6 + PySide6-WebEngine
run.sh / run.bat         # Mac / Windows 启动脚本
muse_quota_widget/
  paths.py               # 平台本地路径（设置、日志、浏览器数据）
  diagnostics.py         # 本地诊断日志（不记令牌与账号 id）
  quota_api.py           # hatch-api 响应解码 + 令牌指纹（参照 ai-quota）
  muse_session.py        # 内存会话 + hatch-api 直连（令牌不存盘）
  settings_store.py      # 刷新频率本地设置（只存分钟数）
  pace.py                # 用量节奏纯计算（与界面无关，可单测）
  pace_widget.py         # 节奏刻度手绘控件（渐变 + 白线 + 白点）
  web_auth.py            # 网页登录换令牌共用逻辑（可见窗与后台窗共用）
  webengine.py           # QtWebEngine 懒加载 + 共享持久化 Profile
  login_window.py        # 内置 QtWebEngine 登录窗口 + /api/auth/check
  background_login.py    # 后台自动登录（离屏浏览器窗，复用 Cookie）
  main_window.py         # 悬浮窗 + 齿轮设置面板 + 边缘隐藏 + 额度刷新线程
```
