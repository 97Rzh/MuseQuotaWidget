"""内置登录窗口：参照 ai-quota 的 MuseWebSession（macOS WKWebView），
Qt 版用 QtWebEngine（Chromium）重写。

浏览器数据用共享的持久化 Profile，登录 Cookie 持久化在
app_dir/QtWebEngine 里，下次打开登录窗口时若会话未过期可直接验证，
无需重新输入密码。令牌本身只进 MuseSession 的内存，窗口关闭
也不会把它写盘。只有在真实额度响应通过解码后，窗口才算验证成功
并关闭；失败时窗口保持打开，可重试。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from . import diagnostics
from .muse_session import MuseSession
from .quota_api import MuseAuthException, MuseAuthKind, QuotaData
from .web_auth import AUTH_JS, POLL_JS, process_auth_result
from .webengine import get_profile, import_error, try_import_webengine

# 验证按钮样式：跟设置面板里的主按钮同一个 RamanVista 语义，
# 主色浅蓝 #4FC3F7、深色字 #101010，之前这里没设任何样式，
# 走的是系统默认的浅灰按钮，在登录窗里一点都不像主操作。
# 悬停变亮、按下变深、禁用变灰，三个状态都写明，避免只改
# 正常态、禁用时还是系统灰、看起来像没反应。
VERIFY_BUTTON_STYLE = """
QPushButton {
  background-color: #4FC3F7;
  color: #101010;
  border: none;
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 14px;
  font-weight: bold;
  min-height: 20px;
}
QPushButton:hover { background-color: #6ED0F9; }
QPushButton:pressed { background-color: #2E9BD6; }
QPushButton:disabled {
  background-color: #3A3D45;
  color: #AEB4C0;
}
"""


class LoginDialog(QDialog):
    def __init__(self, session: MuseSession, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录 Muse")
        self.resize(900, 700)
        self._session = session
        self.verified_quota: Optional[QuotaData] = None
        self._auth_result_text: Optional[str] = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_deadline_ms = 0
        self._fetch_thread = None
        self._fetch_worker = None

        layout = QVBoxLayout(self)
        QWebEngineView, QWebEnginePage, _ = try_import_webengine()
        if QWebEngineView is None or QWebEnginePage is None:
            self._webview = None
            detail = import_error() or "未知导入错误"
            layout.addWidget(QLabel(f"QtWebEngine 不可用：{detail}\n请运行：python3 -m pip install PySide6-WebEngine 后再试。"))
        else:
            self._webview = QWebEngineView(self)
            self._webview.setPage(QWebEnginePage(get_profile(), self._webview))
            self._webview.load(QUrl("https://muse.ai/"))
            layout.addWidget(self._webview, 1)

        self.status_label = QLabel("在上方登录 muse.ai，然后点“验证登录并读取额度”。")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.verify_button = QPushButton("验证登录并读取额度")
        self.verify_button.setStyleSheet(VERIFY_BUTTON_STYLE)
        self.verify_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.verify_button.clicked.connect(self._on_verify_clicked)
        if self._webview is None:
            self.verify_button.setEnabled(False)
        layout.addWidget(self.verify_button)

    def _on_verify_clicked(self) -> None:
        if self._webview is None:
            return
        self.verify_button.setEnabled(False)
        self._stage = "登录检查"
        self.status_label.setText("正在检查 Muse 网页登录…")
        self._auth_result_text = None
        # QtWebEngine 的 runJavaScript 是异步回调，不能直接等 Promise：
        # JS 同步启动 fetch，把结果写进 window 变量，Python 用定时器轮询这个变量。
        # 这与 C# 版 WebView2 的轮询写法是同一招（ExecuteScriptAsync 也不等 Promise）。
        page = self._webview.page()
        page.runJavaScript(AUTH_JS, lambda _result: None)
        from PySide6.QtCore import QDateTime

        self._poll_deadline_ms = QDateTime.currentMSecsSinceEpoch() + 15000
        self._poll_timer.start()

    def _on_poll_tick(self) -> None:
        from PySide6.QtCore import QDateTime

        if self._webview is None:
            self._poll_timer.stop()
            return
        page = self._webview.page()

        def _got(result):
            if isinstance(result, str) and result.strip():
                self._auth_result_text = result
                self._poll_timer.stop()
                self._process_auth_result()
            elif QDateTime.currentMSecsSinceEpoch() > self._poll_deadline_ms:
                self._poll_timer.stop()
                diagnostics.log("auth timeout: window.__museQuotaAuthResult never set")
                self._fail(MuseAuthException(MuseAuthKind.NETWORK_UNAVAILABLE))

        page.runJavaScript(POLL_JS, _got)

    def _process_auth_result(self) -> None:
        try:
            if self._webview is None:
                raise MuseAuthException(MuseAuthKind.NETWORK_UNAVAILABLE)
            url = self._webview.url().toString()
            if not url.startswith("https://muse.ai/"):
                raise MuseAuthException(MuseAuthKind.LOGIN_REQUIRED)
            if self._auth_result_text is None:
                raise MuseAuthException(MuseAuthKind.NETWORK_UNAVAILABLE)
            credential = process_auth_result(self._auth_result_text, self._session.credential)
            if credential is not None:
                self._session.set_credential(credential)
            elif not self._session.has_token:
                raise MuseAuthException(MuseAuthKind.TOKEN_UNAVAILABLE)
            # credential 为 None 且已有同指纹旧令牌时，复用旧令牌。
        except MuseAuthException as e:
            self._fail(e)
            return

        self._stage = "额度读取"
        self.status_label.setText("网页登录已通过，正在读取真实额度…")
        self._start_fetch()

    def _start_fetch(self) -> None:
        from PySide6.QtCore import QObject, QThread, Signal

        class _Worker(QObject):
            done = Signal(object, object)  # quota, error

            def __init__(self, session):
                super().__init__()
                self._session = session

            def run(self):
                try:
                    self.done.emit(self._session.fetch_quota(), None)
                except Exception as e:  # noqa: BLE001 - 转发给主线程按种类处理
                    self.done.emit(None, e)

        thread = QThread(self)
        worker = _Worker(self._session)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_fetch_done)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._fetch_thread = thread
        self._fetch_worker = worker
        thread.start()

    def _on_fetch_done(self, quota, error) -> None:
        if error is not None:
            if isinstance(error, MuseAuthException):
                self._fail(error)
            else:
                self.status_label.setText(f"验证未通过（额度读取）：网络请求失败或超时。请稍后重试。（{error}）")
                self.verify_button.setEnabled(True)
            return
        self.verified_quota = quota
        self.accept()

    def _fail(self, error: MuseAuthException) -> None:
        if error.kind in (
            MuseAuthKind.LOGIN_REQUIRED,
            MuseAuthKind.ACCOUNT_CHANGED,
            MuseAuthKind.TOKEN_UNAVAILABLE,
            MuseAuthKind.INVALID_RESPONSE,
        ):
            # 身份不确定时不保留旧令牌，避免把别人的额度当成自己的。
            self._session.clear()
        stage = getattr(self, "_stage", "登录检查")
        self.status_label.setText(
            f"验证未通过（{stage}）：{error.message_zh}（诊断日志：点齿轮 → 打开诊断日志）"
        )
        self.verify_button.setEnabled(True)
