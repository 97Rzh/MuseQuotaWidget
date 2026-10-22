"""后台登录：启动时自动登录就靠它，用户看不到它。

做法：窗口移到屏幕外（-10000, -10000）再显示，但浏览器仍在正常加载；
用与可见登录窗完全相同的持久化 Profile，所以上次登录留下的 Cookie 还在，
加载 muse.ai 后直接用它换令牌，不用用户再点一次登录。
换到令牌或确认换不到后立即关闭自己，不常驻。
只有一种情况会失败后仍需手动登录：Cookie 已过期、被清除，
或 Muse 要求重新验证——那时后台窗不会弹出来打扰用户，
主窗口只显示“未登录”，用户点齿轮 → 登录即可。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QDateTime, QTimer, QUrl, Signal, QObject
from PySide6.QtWidgets import QWidget

from . import diagnostics
from .muse_session import MuseSession
from .quota_api import MuseAuthException, MuseAuthKind, MuseCredential
from .web_auth import AUTH_JS, POLL_JS, process_auth_result
from .webengine import get_profile, try_import_webengine


class BackgroundLogin(QObject):
    finished = Signal(object)  # MuseCredential 或 None

    def __init__(self, session: MuseSession, parent=None):
        super().__init__(parent)
        self._session = session
        self._view = None
        self._window = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._auth_result_text: Optional[str] = None
        self._poll_deadline_ms = 0
        self._done = False

    def start(self) -> None:
        QWebEngineView, QWebEnginePage, _ = try_import_webengine()
        if QWebEngineView is None or QWebEnginePage is None:
            diagnostics.log("background login failed: QtWebEngine unavailable")
            self.finished.emit(None)
            return
        try:
            window = QWidget()
            window.setWindowTitle("")
            window.resize(800, 600)
            window.move(-10000, -10000)
            view = QWebEngineView(window)
            view.setPage(QWebEnginePage(get_profile(), view))
            # 离屏窗口仍需 show 才会真正加载，但坐标在屏幕外，用户看不到。
            window.show()
            self._window = window
            self._view = view
            view.loadFinished.connect(self._on_load_finished)
            view.load(QUrl("https://muse.ai/"))
            # 导航超时保护：20 秒没完成按失败处理，不卡住启动。
            QTimer.singleShot(20000, self._on_navigation_timeout)
        except Exception:
            diagnostics.log("background login error: init failed")
            self._finish(None)

    def _on_navigation_timeout(self) -> None:
        if self._done or self._view is None:
            return
        # 如果已经在轮询 auth 结果，就不被导航超时打断。
        if self._poll_timer.isActive():
            return
        diagnostics.log("background login: navigation failed or timed out")
        self._finish(None)

    def _on_load_finished(self, ok: bool) -> None:
        if self._done or self._view is None:
            return
        if not ok:
            diagnostics.log("background login: navigation failed or timed out")
            self._finish(None)
            return
        # 重定向链可能让第一次导航完成时地址还不是最终的 muse.ai，
        # 等地址落到 muse.ai 再换令牌，最多再等 5 秒。
        self._wait_for_muse_url(0)

    def _wait_for_muse_url(self, waited_ms: int) -> None:
        if self._done or self._view is None:
            return
        url = self._view.url().toString()
        if url.startswith("https://muse.ai/"):
            self._start_auth()
            return
        if waited_ms >= 5000:
            diagnostics.log("background login: url never reached muse.ai")
            self._finish(None)
            return
        QTimer.singleShot(250, lambda: self._wait_for_muse_url(waited_ms + 250))

    def _start_auth(self) -> None:
        if self._view is None:
            self._finish(None)
            return
        self._auth_result_text = None
        self._view.page().runJavaScript(AUTH_JS, lambda _r: None)
        self._poll_deadline_ms = QDateTime.currentMSecsSinceEpoch() + 15000
        self._poll_timer.start()

    def _on_poll_tick(self) -> None:
        if self._view is None:
            self._poll_timer.stop()
            self._finish(None)
            return

        def _got(result):
            if self._done:
                return
            if isinstance(result, str) and result.strip():
                self._poll_timer.stop()
                self._auth_result_text = result
                self._process_result()
            elif QDateTime.currentMSecsSinceEpoch() > self._poll_deadline_ms:
                self._poll_timer.stop()
                diagnostics.log("auth timeout: window.__museQuotaAuthResult never set")
                self._finish(None)

        self._view.page().runJavaScript(POLL_JS, _got)

    def _process_result(self) -> None:
        try:
            if self._auth_result_text is None:
                raise MuseAuthException(MuseAuthKind.NETWORK_UNAVAILABLE)
            credential = process_auth_result(self._auth_result_text, self._session.credential)
            if credential is not None:
                self._finish(credential)
            else:
                # 本次没给新令牌但指纹与旧凭据一致时，复用旧令牌；
                # 启动时旧凭据为空，所以这里正常情况下不会走到。
                self._finish(self._session.credential)
        except MuseAuthException as e:
            diagnostics.log(f"background login failed: {e.kind}")
            self._finish(None)
        except Exception:
            diagnostics.log("background login error: process failed")
            self._finish(None)

    def _finish(self, credential: Optional[MuseCredential]) -> None:
        if self._done:
            return
        self._done = True
        self._poll_timer.stop()
        try:
            if self._window is not None:
                self._window.close()
                self._window.deleteLater()
        except Exception:
            pass
        self._view = None
        self._window = None
        self.finished.emit(credential)
