"""QtWebEngine 的懒加载与共享 Profile。

为什么懒加载：主悬浮窗本身不需要浏览器，只有登录 / 后台自动登录
才需要 QtWebEngine；如果这台机器的 PySide6 里没有 WebEngine，
主窗仍能打开、只显示“未登录”，登录时再明确报错，而不是一启动就崩。

Profile 共享：登录窗与后台登录窗用同一个持久化 Profile，
Cookie 就存在 app_dir/QtWebEngine 里，相当于 C# 版的
WebView2 数据文件夹；后台登录能复用登录窗留下的 Cookie。

Qt6 的模块划分（2026-10-23 Mac 实测教训，别再按 Qt5 写）：
QWebEngineView 在 QtWebEngineWidgets，
QWebEnginePage 与 QWebEngineProfile 都在 QtWebEngineCore。
以前的代码把 QWebEnginePage 也写在 Widgets 里，WebEngine 装上
之后照样报：cannot import name 'QWebEnginePage' from
'PySide6.QtWebEngineWidgets'，因为那个 .so 里根本没有这个名字。
"""

from __future__ import annotations

from typing import Optional

from .paths import webengine_dir

_profile = None
_import_error: Optional[str] = None


def try_import_webengine():
    """返回 (QWebEngineView, QWebEnginePage, QWebEngineProfile)，失败返回 (None, None, None)。"""
    global _import_error
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView

        try:
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        except ImportError:
            # 极老版本才把 Page/Profile 放 Widgets 里，留作兼容兜底。
            from PySide6.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile  # type: ignore

        return QWebEngineView, QWebEnginePage, QWebEngineProfile
    except Exception as e:  # ImportError 等都按缺失处理，不崩主窗。
        _import_error = str(e)
        return None, None, None


def import_error() -> Optional[str]:
    return _import_error


def get_profile():
    """共享的持久化 Profile，第一次调用时创建。调用方须保证 WebEngine 已可导入。"""
    global _profile
    if _profile is not None:
        return _profile
    _, _, QWebEngineProfile = try_import_webengine()
    if QWebEngineProfile is None:
        raise RuntimeError("QtWebEngine 不可用")
    profile = QWebEngineProfile("MuseQuotaWidget")
    base = str(webengine_dir())
    try:
        profile.setPersistentStoragePath(base)
        profile.setCachePath(base + "/cache")
        try:
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
            )
        except Exception:
            pass
    except Exception:
        pass
    _profile = profile
    return profile
