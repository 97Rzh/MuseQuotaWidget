"""MuseQuotaWidget：Python 跨平台版（Mac / Windows）。

悬浮窗 + 登录窗用 PySide6（Qt），登录窗用 QtWebEngine（Chromium），
与 C# 版的 WebView2 路线对应：内置浏览器登录 muse.ai，
同源 POST /api/auth/check 换令牌，令牌只存内存，
再用令牌 GET hatch-api 读额度。C# 版已整段删除，
git 历史（5337ffe 及之前）里还能找回。
"""

__version__ = "1.0.0"
