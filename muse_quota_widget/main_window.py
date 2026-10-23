"""悬浮窗本体：无边框、圆角、默认始终置顶，可拖动。

正常时只显示额度：剩余百分比大字 + 主条 + 节奏刻度 + 重置时间，
不显示标题、计划、已用、额外词元等字样。
没有右键菜单：右上角齿轮按钮只在鼠标悬停时显示，平时不显示；
点齿轮后额度区缩到左上角（大字 44→28、居中→左对齐），
窗体从 240 宽放大到 528 宽，右侧出现 RamanVista 风格的设置面板；
再点齿轮或面板里的“完成”可收回。

边缘停靠：把悬浮窗拖到屏幕边缘附近（40px 内）再双击，
窗体滑到屏幕外、只在边缘留一条 8px 的线；鼠标划过这条线
时窗体滑出来，鼠标离开窗体时又滑回去；把滑出来的窗体
拖离边缘，就取消停靠、恢复成普通悬浮窗。设置面板展开时
不触发停靠，点齿轮展开设置会先取消停靠。

控件风格参考 RamanVista：深色表面 #2B2D33 / #25272D、
边框 #606060、主色浅蓝 #4FC3F7、卡片圆角 12、按钮圆角 6、
滑块拇指 #4FC3F7（不引 MaterialDesign 包，只复刻颜色与样式）。

额度读取在后台线程做，不卡界面；令牌只存内存，不存盘。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import diagnostics, settings_store
from .background_login import BackgroundLogin
from .login_window import LoginDialog
from .muse_session import MuseSession
from .pace import compute_pace
from .pace_widget import PaceScaleWidget
from .paths import log_path
from .quota_api import MuseAuthException, MuseAuthKind, QuotaData
from .webengine import import_error, try_import_webengine

# RamanVista 语义色
SURFACE = "#2B2D33"
SURFACE_STRONG = "#25272D"
SURFACE_ALT = "#3A3D45"
BORDER_COLOR = "#606060"
TEXT_COLOR = "#FFFFFF"
SECONDARY_TEXT = "#C9CDD6"
MUTED_TEXT = "#AEB4C0"
ACCENT = "#4FC3F7"
ACCENT_HOVER = "#6ED0F9"
HOVER_BG = "#36414D"

CARD_STYLE = """
QWidget#card {
  background-color: rgba(31, 41, 55, 232);
  border: 1px solid rgba(255, 255, 255, 51);
  border-radius: 16px;
}
"""

PRIMARY_BUTTON_STYLE = f"""
QPushButton {{
  background-color: {ACCENT};
  color: #101010;
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 13px;
}}
QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton:disabled {{ opacity: 0.55; }}
"""

SECONDARY_BUTTON_STYLE = f"""
QPushButton {{
  background-color: {SURFACE_ALT};
  color: {TEXT_COLOR};
  border: 1px solid {BORDER_COLOR};
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 13px;
}}
QPushButton:hover {{
  background-color: {HOVER_BG};
  border: 1px solid {ACCENT};
}}
QPushButton:disabled {{ opacity: 0.55; }}
"""

DANGER_BUTTON_STYLE = f"""
QPushButton {{
  background-color: {SURFACE_ALT};
  color: #F87171;
  border: 1px solid {BORDER_COLOR};
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 13px;
}}
QPushButton:hover {{
  background-color: #422A2A;
  border: 1px solid #F87171;
}}
"""

GEAR_BUTTON_STYLE = """
QPushButton {
  background-color: transparent;
  border: none;
  border-radius: 14px;
  color: #9CA3AF;
  font-size: 16px;
}
QPushButton:hover { background-color: rgba(255, 255, 255, 51); }
"""

SETTINGS_CARD_STYLE = f"""
QWidget#settingsCard {{
  background-color: {SURFACE_STRONG};
  border: 1px solid {BORDER_COLOR};
  border-radius: 12px;
}}
"""

SLIDER_STYLE = f"""
QSlider::groove:horizontal {{
  height: 4px;
  background-color: {SURFACE_ALT};
  border-radius: 2px;
}}
QSlider::handle:horizontal {{
  width: 12px;
  height: 12px;
  margin: -6px 0;
  background-color: {ACCENT};
  border-radius: 6px;
}}
QSlider::sub-page:horizontal {{
  background-color: {ACCENT};
  border-radius: 2px;
}}
"""


def _remaining_color(remaining: float) -> str:
    if remaining < 20:
        return "#F87171"
    if remaining < 50:
        return "#FBBF24"
    return "#4ADE80"


class _FetchWorker(QObject):
    done = Signal(object, object)  # quota, error

    def __init__(self, session: MuseSession):
        super().__init__()
        self._session = session

    def run(self):
        try:
            self.done.emit(self._session.fetch_quota(), None)
        except Exception as e:  # noqa: BLE001 - 转发给主线程按种类处理
            self.done.emit(None, e)


class FloatingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("")
        # 兜底：直接建 FloatingWindow 时也设一次图标，
        # 不经过 main.py 时任务栏 / Dock 仍显示做的那个图标。
        try:
            from .app_icon import load_app_icon

            _icon = load_app_icon()
            if _icon is not None:
                self.setWindowIcon(_icon)
        except Exception:
            pass
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(240, 180)
        # 宽度由设置面板开关控制，不由布局说了算：Mac 上只调 resize()
        # 会被布局最小宽度顶住，收回后仍停在 528 宽（2026-10-23 实测）。
        # 固定宽度后，节奏文字再长、设置面板再宽都撑不开窗体。
        self.setFixedWidth(240)

        self._session = MuseSession()
        self._last_good: Optional[QuotaData] = None
        self._is_settings_expanded = False
        self._suppress_slider_apply = False
        self._drag_pos = None
        # 边缘停靠状态：_docked_edge 为 None = 未停靠，
        # 否则为 'left'/'right'/'top'/'bottom'；_docked_hidden 为 True
        # 表示当前正滑在屏幕外、只留一条线。
        self._docked_edge = None
        self._docked_hidden = False
        self._dock_line = 8
        self._dock_threshold = 40
        self._background_login = None
        self._fetch_thread = None
        self._fetch_worker = None

        self._refresh_interval_minutes = settings_store.load_interval_minutes()
        self._timer = QTimer(self)
        self._timer.setInterval(self._refresh_interval_minutes * 60 * 1000)
        self._timer.timeout.connect(self._load_quota)
        self._timer.start()

        # ---- 卡片 ----
        card = QWidget(self)
        card.setObjectName("card")
        card.setStyleSheet(CARD_STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 12)
        card_layout.setSpacing(0)

        # ---- 额度区 ----
        self.quota_widget = QWidget()
        quota_layout = QVBoxLayout(self.quota_widget)
        quota_layout.setContentsMargins(0, 0, 0, 0)
        quota_layout.setSpacing(0)

        self.remaining_label = QLabel("—")
        self.remaining_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(44)
        font.setBold(True)
        self.remaining_label.setFont(font)
        self.remaining_label.setStyleSheet(f"color: #4ADE80;")
        quota_layout.addWidget(self.remaining_label)

        self.remaining_bar = QProgressBar()
        self.remaining_bar.setRange(0, 100)
        self.remaining_bar.setValue(0)
        self.remaining_bar.setTextVisible(False)
        self.remaining_bar.setFixedHeight(10)
        self._set_bar_color("#22C55E")
        quota_layout.addWidget(self.remaining_bar, 0)
        quota_layout.setSpacing(8)

        # 节奏区
        self.pace_widget = QWidget()
        pace_layout = QVBoxLayout(self.pace_widget)
        pace_layout.setContentsMargins(0, 0, 0, 0)
        pace_layout.setSpacing(0)
        self.pace_scale = PaceScaleWidget()
        pace_layout.addWidget(self.pace_scale)
        pace_labels = QHBoxLayout()
        pace_labels.setContentsMargins(0, 2, 0, 0)
        for text, align in (("慢", Qt.AlignLeft), ("平均", Qt.AlignCenter), ("快", Qt.AlignRight)):
            lbl = QLabel(text)
            lbl.setAlignment(align)
            lbl.setStyleSheet(f"color: #9CA3AF; font-size: 10px;")
            pace_labels.addWidget(lbl, 1)
        pace_layout.addLayout(pace_labels)
        self.pace_label = QLabel("—")
        self.pace_label.setAlignment(Qt.AlignCenter)
        pace_font = QFont()
        pace_font.setBold(True)
        pace_font.setPointSize(12)
        self.pace_label.setFont(pace_font)
        pace_layout.addWidget(self.pace_label)
        self.pace_widget.setVisible(False)
        quota_layout.addWidget(self.pace_widget)

        self.time_label = QLabel("未登录")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        quota_layout.addWidget(self.time_label)

        card_layout.addWidget(self.quota_widget, 1)

        # ---- 设置面板 ----
        self.settings_widget = QWidget()
        self.settings_widget.setObjectName("settingsCard")
        self.settings_widget.setStyleSheet(SETTINGS_CARD_STYLE)
        self.settings_widget.setFixedWidth(300)
        self.settings_widget.setVisible(False)
        settings_layout = QVBoxLayout(self.settings_widget)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(0)

        def section(text: str) -> None:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {MUTED_TEXT}; font-size: 12px; font-weight: bold;")
            settings_layout.addWidget(lbl)

        def spacer(height: int = 6) -> None:
            settings_layout.addSpacing(height)

        title = QLabel("设置")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {TEXT_COLOR};")
        settings_layout.addWidget(title)

        spacer(16)
        section("账号")
        spacer(6)
        self.login_status_label = QLabel("未登录")
        self.login_status_label.setStyleSheet(f"color: {SECONDARY_TEXT}; font-size: 13px;")
        settings_layout.addWidget(self.login_status_label)
        spacer(8)
        account_row = QHBoxLayout()
        account_row.setSpacing(8)
        self.login_button = QPushButton("登录 Muse…")
        self.login_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.login_button.clicked.connect(self._on_login_clicked)
        account_row.addWidget(self.login_button, 1)
        self.logout_button = QPushButton("退出登录")
        self.logout_button.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.logout_button.clicked.connect(self._on_logout_clicked)
        account_row.addWidget(self.logout_button, 1)
        settings_layout.addLayout(account_row)

        spacer(16)
        section("数据")
        spacer(6)
        refresh_button = QPushButton("刷新数据")
        refresh_button.setStyleSheet(SECONDARY_BUTTON_STYLE)
        refresh_button.clicked.connect(self._on_refresh_clicked)
        settings_layout.addWidget(refresh_button)

        spacer(16)
        section("刷新频率")
        spacer(6)
        self.interval_slider = QSlider(Qt.Horizontal)
        self.interval_slider.setRange(1, 60)
        self.interval_slider.setSingleStep(1)
        self.interval_slider.setStyleSheet(SLIDER_STYLE)
        self.interval_slider.valueChanged.connect(self._on_interval_changed)
        settings_layout.addWidget(self.interval_slider)
        self.interval_value_label = QLabel(f"每 {self._refresh_interval_minutes} 分钟刷新")
        self.interval_value_label.setAlignment(Qt.AlignCenter)
        self.interval_value_label.setStyleSheet(f"color: {TEXT_COLOR}; font-size: 14px;")
        settings_layout.addWidget(self.interval_value_label)
        note = QLabel("读的是额度接口，不是对话，不耗对话 token；过于频繁可能触发限流，建议 5 分钟以上。拖动滑块立即生效，不用点确定。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {MUTED_TEXT}; font-size: 11px;")
        settings_layout.addWidget(note)

        spacer(16)
        section("显示")
        spacer(6)
        self.topmost_checkbox = QCheckBox("始终置顶")
        self.topmost_checkbox.setStyleSheet(f"color: {TEXT_COLOR}; font-size: 13px;")
        self.topmost_checkbox.setChecked(True)
        self.topmost_checkbox.clicked.connect(self._on_topmost_clicked)
        settings_layout.addWidget(self.topmost_checkbox)

        spacer(16)
        section("其他")
        spacer(6)
        log_button = QPushButton("打开诊断日志")
        log_button.setStyleSheet(SECONDARY_BUTTON_STYLE)
        log_button.clicked.connect(self._on_open_log_clicked)
        settings_layout.addWidget(log_button)
        spacer(8)
        exit_button = QPushButton("退出软件")
        exit_button.setStyleSheet(DANGER_BUTTON_STYLE)
        exit_button.clicked.connect(self.close)
        settings_layout.addWidget(exit_button)

        spacer(16)
        complete_button = QPushButton("完成")
        complete_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        complete_button.clicked.connect(self._toggle_settings)
        settings_layout.addWidget(complete_button)

        card_layout.addWidget(self.settings_widget, 0)
        card_layout.setSpacing(16)

        # ---- 齿轮按钮：悬停才显示，平时不显示 ----
        self.gear_button = QPushButton("⚙")
        self.gear_button.setStyleSheet(GEAR_BUTTON_STYLE)
        self.gear_button.setFixedSize(28, 28)
        self.gear_button.setVisible(False)
        self.gear_button.clicked.connect(self._toggle_settings)
        # 齿轮盖在卡片右上角：用绝对定位，放在卡片布局之上。
        # QWidget 没有 overlay 布局，这里把它设为 card 的子控件并手动定位，
        # 在 resizeEvent 里保持在右上角。
        self.gear_button.setParent(card)
        self.gear_button.raise_()

        self._suppress_slider_apply = True
        self.interval_slider.setValue(self._refresh_interval_minutes)
        self._suppress_slider_apply = False
        self._update_login_status()

        # 拖动：Qt 里点在 QLabel、进度条上时按压事件不一定冒泡到主窗口，
        # 所以给额度区控件装事件过滤器，点按钮、滑块、复选框时不拖，
        # 点其他额度区控件时都拖；设置面板背景不拖，展开后从迷你额度区拖。
        for widget in (
            card,
            self.quota_widget,
            self.remaining_label,
            self.remaining_bar,
            self.pace_widget,
            self.pace_scale,
            self.pace_label,
            self.time_label,
        ):
            widget.installEventFilter(self)

        self._auto_login_and_load()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt 命名
        if isinstance(watched, (QPushButton, QSlider, QCheckBox)):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            # 额度区双击 = 停靠/取消停靠；按钮上的双击不走这里，
            # 上面已经按按钮原样放行了。
            self._on_double_click()
            return True
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            return True
        if event.type() == QEvent.MouseMove and self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            # 一拖动就取消停靠：拖离边缘后不再自动滑回，
            # 想再停靠就拖回边缘重新双击。
            if self._docked_edge is not None:
                self._docked_edge = None
                self._docked_hidden = False
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            return True
        if event.type() == QEvent.MouseButtonRelease:
            self._drag_pos = None
        return super().eventFilter(watched, event)

    # ---- 齿轮与拖动 ----

    def enterEvent(self, event):  # noqa: N802
        self.gear_button.setVisible(True)
        # 停靠在边缘、只留一条线时，鼠标划过这条线就滑出来。
        # 窗体本身就是那条线：滑在外面时可见部分只有 8px，
        # 鼠标进到这 8px 里就会触发 enterEvent。
        if self._docked_edge is not None and self._docked_hidden:
            self._reveal_docked()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.gear_button.setVisible(False)
        # 停靠状态下，鼠标离开整个窗体就滑回去、只留线。
        # 正在拖动时不滑回，否则拖动中窗体一动就被藏起来。
        if self._docked_edge is not None and not self._docked_hidden and self._drag_pos is None:
            self._hide_docked()
        super().leaveEvent(event)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # 齿轮固定在卡片右上角（卡片内边距 16/14 的范围内）。
        if hasattr(self, "gear_button"):
            self.gear_button.move(self.width() - 16 - 28, 14)

    def mousePressEvent(self, event: QMouseEvent):  # noqa: N802
        if event.button() == Qt.LeftButton:
            # 点到按钮、滑块、复选框时不拖动窗口，否则点不下去；
            # 点额度区空白处仍可拖动。
            child = self.childAt(event.position().toPoint())
            if isinstance(child, (QPushButton, QSlider, QCheckBox)):
                self._drag_pos = None
                super().mousePressEvent(event)
                return
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            if self._docked_edge is not None:
                self._docked_edge = None
                self._docked_hidden = False
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):  # noqa: N802
        # 主窗体空白处双击也走停靠；点在按钮上时不触发。
        child = self.childAt(event.position().toPoint())
        if isinstance(child, (QPushButton, QSlider, QCheckBox)):
            super().mouseDoubleClickEvent(event)
            return
        self._on_double_click()
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ---- 设置面板开关 ----

    def _toggle_settings(self) -> None:
        self._is_settings_expanded = not self._is_settings_expanded
        if self._is_settings_expanded:
            # 展开设置面板时先取消停靠：528 宽的面板不适合滑到边外，
            # 而且展开后鼠标离开再滑回会把设置面板也藏到边外。
            # 此时窗体已经是滑出来的状态，取消后就留在屏幕内。
            self._docked_edge = None
            self._docked_hidden = False
            # 先恢复面板宽度再显示，否则面板还压在 0 宽上。
            self.settings_widget.setFixedWidth(300)
            self.settings_widget.setVisible(True)
            self._set_quota_mini(True)
            self._update_login_status()
            target_width = 528
        else:
            self.settings_widget.setVisible(False)
            # 只隐藏不够：布局最小宽度仍可能把 300 宽的面板算进去，
            # 收回后窗体就被顶在 528 宽下不来。直接把面板宽度压到 0。
            self.settings_widget.setFixedWidth(0)
            self._set_quota_mini(False)
            target_width = 240
        # 宽度用固定宽度强制，不用 resize()：resize() 会被布局
        # 最小宽度钳制，Mac 上收回时就卡在展开宽度。高度仍自适应，
        # 以免节奏区出现/消失时把内容裁掉。
        self.setFixedWidth(target_width)
        self.updateGeometry()
        QApplication.processEvents()
        height = self.sizeHint().height()
        # sizeHint 在无边框透明窗上可能偏小，至少保留额度区高度。
        height = max(height, self.quota_widget.sizeHint().height() + 30)
        self.resize(target_width, height)
        self.gear_button.move(self.width() - 16 - 28, 14)
        diagnostics.log(
            f"settings toggled: expanded={self._is_settings_expanded} "
            f"width={self.width()} target={target_width}"
        )

    # ---- 边缘停靠 ----

    def _screen_geometry(self):
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return None
        # availableGeometry 排除菜单栏 / Dock，占的是真正能看见的区域，
        # 停靠到这里线才不会被系统栏盖住。
        return screen.availableGeometry()

    def _on_double_click(self) -> None:
        # 设置面板展开时不触发停靠：528 宽的面板滑到边外没有意义，
        # 先收起面板、再拖到边缘双击才是正常流程。
        if self._is_settings_expanded:
            return
        if self._docked_edge is not None:
            # 已停靠时再双击 = 取消停靠，窗体留在屏幕内不动。
            self._docked_edge = None
            self._docked_hidden = False
            self._reveal_docked()
            return
        geom = self._screen_geometry()
        if geom is None:
            return
        # 到四条边的距离，取最小的那条；离边超过阈值就不停靠，
        # 避免在屏幕中间双击一下就把窗体藏到边上。
        left_dist = self.x() - geom.x()
        right_dist = (geom.x() + geom.width()) - (self.x() + self.width())
        top_dist = self.y() - geom.y()
        bottom_dist = (geom.y() + geom.height()) - (self.y() + self.height())
        edge, dist = min(
            (("left", left_dist), ("right", right_dist), ("top", top_dist), ("bottom", bottom_dist)),
            key=lambda item: item[1],
        )
        if dist > self._dock_threshold:
            return
        self._docked_edge = edge
        self._hide_docked()
        diagnostics.log(f"docked to {edge} (dist={dist})")

    def _docked_position(self):
        """停靠时窗体左上角：屏幕外，只留 _dock_line 宽的线。"""
        geom = self._screen_geometry()
        if geom is None or self._docked_edge is None:
            return None
        line = self._dock_line
        if self._docked_edge == "left":
            return geom.x() - self.width() + line, self.y()
        if self._docked_edge == "right":
            return geom.x() + geom.width() - line, self.y()
        if self._docked_edge == "top":
            return self.x(), geom.y() - self.height() + line
        return self.x(), geom.y() + geom.height() - line

    def _revealed_position(self):
        """滑出来时窗体左上角：贴着同一条边、完整显示在屏幕内。"""
        geom = self._screen_geometry()
        if geom is None or self._docked_edge is None:
            return None
        w, h = self.width(), self.height()
        x, y = self.x(), self.y()
        if self._docked_edge == "left":
            x = geom.x()
            y = max(geom.y(), min(y, geom.y() + geom.height() - h))
        elif self._docked_edge == "right":
            x = geom.x() + geom.width() - w
            y = max(geom.y(), min(y, geom.y() + geom.height() - h))
        elif self._docked_edge == "top":
            y = geom.y()
            x = max(geom.x(), min(x, geom.x() + geom.width() - w))
        else:
            y = geom.y() + geom.height() - h
            x = max(geom.x(), min(x, geom.x() + geom.width() - w))
        return x, y

    def _hide_docked(self) -> None:
        pos = self._docked_position()
        if pos is None:
            return
        self._docked_hidden = True
        self.move(pos[0], pos[1])

    def _reveal_docked(self) -> None:
        pos = self._revealed_position()
        if pos is None:
            return
        self._docked_hidden = False
        self.move(pos[0], pos[1])

    def _set_quota_mini(self, mini: bool) -> None:
        font = QFont()
        font.setBold(True)
        font.setPointSize(28 if mini else 44)
        self.remaining_label.setFont(font)
        self.remaining_label.setAlignment(Qt.AlignLeft if mini else Qt.AlignCenter)
        self.time_label.setAlignment(Qt.AlignLeft if mini else Qt.AlignCenter)
        self.time_label.setStyleSheet(f"color: #9CA3AF; font-size: {10 if mini else 11}px;")
        pace_font = QFont()
        pace_font.setBold(True)
        pace_font.setPointSize(10 if mini else 12)
        self.pace_label.setFont(pace_font)
        self.pace_label.setAlignment(Qt.AlignLeft if mini else Qt.AlignCenter)

    def _update_login_status(self) -> None:
        logged_in = self._session.has_token
        self.login_status_label.setText("已登录" if logged_in else "未登录")
        self.login_status_label.setStyleSheet(
            f"color: {'#4ADE80' if logged_in else SECONDARY_TEXT}; font-size: 13px;"
        )
        self.login_button.setEnabled(not logged_in)
        self.logout_button.setEnabled(logged_in)

    # ---- 面板操作 ----

    def _on_interval_changed(self, value: int) -> None:
        self.interval_value_label.setText(f"每 {value} 分钟刷新")
        if self._suppress_slider_apply:
            return
        # 面板内滑块拖动立即生效并保存，不用再点确定/取消。
        self._set_refresh_interval(value)

    def _set_refresh_interval(self, minutes: int) -> None:
        self._refresh_interval_minutes = max(1, min(60, minutes))
        self._timer.setInterval(self._refresh_interval_minutes * 60 * 1000)
        settings_store.save_interval_minutes(self._refresh_interval_minutes)
        if self._last_good is not None:
            self._show(self._last_good)
        # 没有上次快照时不碰时间行：启动时时间行可能是“自动登录中…”。

    def _on_topmost_clicked(self) -> None:
        checked = self.topmost_checkbox.isChecked()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()

    def _on_open_log_clicked(self) -> None:
        path = log_path()
        if path.exists():
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", str(path)], check=False)
                elif sys.platform == "win32":
                    subprocess.run(["start", "", str(path)], shell=True, check=False)
                else:
                    subprocess.run(["xdg-open", str(path)], check=False)
            except Exception:
                pass
        else:
            self.time_label.setText("无诊断日志")

    def _on_login_clicked(self) -> None:
        if try_import_webengine()[0] is None:
            # 以前这里只说“重新安装 PySide6”，把真实原因藏起来了，
            # 导致用户按提示重装了 PySide6 还是缺 WebEngine。
            # 现在把真实导入错误打出来，并直接给对的包名。
            detail = import_error() or "未知导入错误"
            QMessageBox.warning(
                self,
                "登录不可用",
                f"QtWebEngine 不可用：{detail}\n"
                "请运行：python3 -m pip install PySide6-WebEngine 后再试。\n"
                "主悬浮窗仍可打开，额度要等登录可用后才能读取。",
            )
            return
        dialog = LoginDialog(self._session, self)
        if dialog.exec() == 1 and dialog.verified_quota is not None:  # QDialog.Accepted
            self._last_good = dialog.verified_quota
            self._show(dialog.verified_quota)

    def _on_logout_clicked(self) -> None:
        # 只清内存里的令牌与指纹，不删浏览器数据文件夹：
        # 网页登录 Cookie 仍在本地，下次打开登录窗口时若会话未过期
        # 可直接验证，无需重新输入密码。彻底退出请手动删除
        # app_dir/QtWebEngine 文件夹。
        self._session.clear()
        self.time_label.setText("未登录")
        self.pace_widget.setVisible(False)
        self._update_login_status()
        # 退出登录不收起设置面板：用户能直接看到状态变回“未登录”。

    def _on_refresh_clicked(self) -> None:
        if self._session.has_token:
            self._load_quota()
        else:
            self._auto_login_and_load()

    # ---- 额度读取 ----

    def _auto_login_and_load(self) -> None:
        if not self._session.has_token:
            self.time_label.setText("自动登录中…")
            if try_import_webengine()[0] is None:
                diagnostics.log("background login failed: QtWebEngine unavailable")
                self._load_quota()
                return
            background = BackgroundLogin(self._session, self)
            self._background_login = background

            def _finished(credential):
                if credential is not None:
                    self._session.set_credential(credential)
                self._load_quota()

            background.finished.connect(_finished)
            background.start()
        else:
            self._load_quota()

    def _load_quota(self) -> None:
        if not self._session.has_token:
            # 未登录时只显示“未登录”，百分比保持上次的（或初始的 —），
            # 不拿旧数据冒充新数据。
            self.time_label.setText("未登录")
            self._update_login_status()
            return
        thread = QThread(self)
        worker = _FetchWorker(self._session)
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
            if isinstance(error, MuseAuthException) and error.kind in (
                MuseAuthKind.LOGIN_REQUIRED,
                MuseAuthKind.ACCOUNT_CHANGED,
                MuseAuthKind.TOKEN_UNAVAILABLE,
            ):
                # 登录失效时清掉内存令牌；时间行只写短提示，
                # 百分比与条保持上次成功值，不清空。
                self._session.clear()
                self.time_label.setText("登录已失效")
                self._update_login_status()
            else:
                # 网络、限流等临时失败：不丢令牌，下次定时刷新再试。
                self.time_label.setText("读取失败")
            return
        self._last_good = quota
        self._show(quota)

    def _set_bar_color(self, color: str) -> None:
        self.remaining_bar.setStyleSheet(
            f"""
            QProgressBar {{
              background-color: rgba(255, 255, 255, 51);
              border: none;
              border-radius: 5px;
              height: 10px;
            }}
            QProgressBar::chunk {{
              background-color: {color};
              border-radius: 5px;
            }}
            """
        )

    def _show(self, data: QuotaData) -> None:
        # 极简版：只显示周额度剩余百分比 + 一条，不显示标题、
        # 计划、已用、额外词元等任何字样。时间行只放刷新时间
        # （每周额度重置时间），不带任何前缀字样。
        remaining = max(0.0, min(100.0, data.remaining))
        self.remaining_label.setText(f"{remaining:.0f}%")
        color = _remaining_color(remaining)
        self.remaining_label.setStyleSheet(f"color: {color};")
        self.remaining_bar.setValue(int(remaining))
        self._set_bar_color(color)

        # 刷新时间：解码时已转本地时间，这里直接按本地格式化，
        # 保证 UTC 返回的时间显示为本地时间，不显示 UTC。
        self.time_label.setText(
            data.weekly_reset_at.strftime("%m-%d %H:%M") if data.weekly_reset_at is not None else ""
        )

        self._show_pace(data, remaining)
        self._update_login_status()
        # 停靠在外面时，额度刷新可能改变窗体高度（节奏区出现/消失），
        # 高度变了停靠位置也要跟着重算，否则留的线会变宽或变窄。
        if self._docked_edge is not None and self._docked_hidden:
            self._hide_docked()

    def _show_pace(self, data: QuotaData, remaining: float) -> None:
        if data.weekly_reset_at is None:
            self.pace_widget.setVisible(False)
            return
        # 节奏按现在这一刻算，不按快照的更新时间算，
        # 所以时间过去后即使额度没刷新，节奏也会跟着动。
        now = datetime.now().astimezone()
        reset_local = data.weekly_reset_at
        if reset_local.tzinfo is None:
            reset_local = reset_local.replace(tzinfo=now.tzinfo)
        else:
            reset_local = reset_local.astimezone(now.tzinfo)
        pace = compute_pace(reset_local, now, remaining)
        self.pace_scale.set_fraction(pace.fraction)
        self.pace_label.setText(pace.text)
        self.pace_label.setStyleSheet(f"color: {pace.color};")
        self.pace_widget.setVisible(True)
