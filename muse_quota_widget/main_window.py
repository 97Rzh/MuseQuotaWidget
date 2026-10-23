"""悬浮窗本体：无边框、圆角、默认始终置顶，可拖动。

正常时只显示额度：剩余百分比大字 + 主条 + 节奏刻度 + 重置时间，
不显示标题、计划、已用、额外词元等字样。
没有右键菜单：右上角齿轮按钮只在鼠标悬停时显示，平时不显示；
点齿轮后额度区缩到左上角（大字 44→28、居中→左对齐），
窗体从 240 宽放大到 528 宽，右侧出现 RamanVista 风格的设置面板；
再点齿轮或面板里的“完成”可收回。

边缘隐藏（取代旧的双击停靠 + 8px 线）：
- 窗体永远拖不出屏幕：拖动全程按所有屏的虚拟外框钳制，
  且至少交叠一屏，双屏之间可以自由拖过去，不会一半滑到
  屏幕外、也不会拖进高低错开的屏上方死角回不来；
  屏间交界不算边，拖过交界不会触发吸入 / 隐藏，
  只有拖到某屏真正的上 / 下 / 最左 / 最右外边才会触发。
- 拖到边缘松手就自动隐藏：不再需要双击，松手时窗体
  只要贴着边（5px 内），就变成贴在边上的一条 96x48 小条，
  条里只显示剩余额度（跟主窗同色，绿 / 黄 / 红随剩余额度变）。
- 划过小条就展开：鼠标划过小条，窗体在边上完整展开；
  鼠标离开完整窗体，又变回小条；把展开后的窗体拖离边缘，
  就取消隐藏、恢复成普通悬浮窗。
设置面板展开时不触发隐藏，点齿轮展开设置会先取消隐藏。

边缘灵魂抽取动画：拖动完整窗体靠近某条边（180px 内）时，
那条边上出现一条灵魂带：从窗体边伸向边口的半透明发光带，
带宽是窗体沿边尺寸的 60%，窗体边亮、边口处淡出，
带子里有光点带着淡尾从窗体边漂向边口、越近边口越淡；
窗体不再被轻吸，窗体跟鼠标走，灵魂带自己从窗体边流向边口。
松手贴边后不再瞬间切小条，而是 600ms 形变过渡：窗体
按 easeInOut 滑向边、缩小、透明度先跌到 0.2 再亮回 1.0，
中途在最暗处换成小条内容，最后定在小条上，像灵魂被抽走
后又在小条里重聚。灵魂带是独立的 Tool 悬浮层，不抢鼠标、
不抢焦点，只在拖动时出现，松手、拖离、展开设置时都消失。
双屏屏间交界不算边，拖过交界不会出灵魂带、不会变小条。

控件风格参考 RamanVista：深色表面 #2B2D33 / #25272D、
边框 #606060、主色浅蓝 #4FC3F7、卡片圆角 12、按钮圆角 6、
滑块拇指 #4FC3F7（不引 MaterialDesign 包，只复刻颜色与样式）。

额度读取在后台线程做，不卡界面；令牌只存内存，不存盘。
"""

from __future__ import annotations

import math
import subprocess
import sys
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen
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


class SuctionOverlay(QWidget):
    """边缘灵魂抽取动画层：像灵魂被抽出窗体、流向边。

    不做任何交互，只画三样东西，没有暗核、没有螺旋、没有热点：
    1) 边上的一道柔和亮线（灵魂要去的口子），带一点脉动；
    2) 一条从窗体边伸向边的灵魂带：不是细线，是一条
       半透明、带波浪边的发光带，窗体边亮、边口处淡出，
       像灵魂的尾巴在消散，带宽是窗体沿边尺寸的 60%，
       从窗体中心伸出，不是铺满整个窗体高度；
    3) 带子里流动的光点 / 光尘：从窗体边出发、向边口漂，
       越近边口越淡（被口子收走），不是越近越亮，
       每个光点后面拖一小段淡尾，看起来就是灵魂在流。
    带子覆盖窗体到边的间隙 + 40px 重叠进窗体边，
    重叠那一段就是窗体边在发光（灵魂正在离开身体）。
    _progress 越近 1 越亮，但远处也有 0.5 的底亮，
    不会 180px 外就淡到看不见。
    """

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._edge = "left"
        self._progress = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._on_tick)

    def _on_tick(self) -> None:
        # 灵魂流动速度：慢而稳，像幽灵在漂，不是闪烁。
        self._phase = (self._phase + 0.025 + self._progress * 0.05) % 1.0
        self.update()

    def show_suction(self, edge: str, x: int, y: int, w: int, h: int, progress: float) -> None:
        self._edge = edge
        self._progress = max(0.0, min(1.0, progress))
        was_visible = self.isVisible()
        self.move(x, y)
        self.resize(w, h)
        if not self._timer.isActive():
            self._timer.start()
        if not was_visible:
            self.show()
            self.raise_()
        # 已显示时不再 raise：拖动每步都 raise 会在 Windows 上
        # 反复改层级、看起来就是闪，move/resize 本身已够刷新。

    def hide_suction(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        if self.isVisible():
            self.hide()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        edge = self._edge
        horizontal = edge in ("left", "right")
        span = h if horizontal else w
        depth = w if horizontal else h
        # 远处也有底亮：0.5 + 0.5*progress，180px 外仍看得见。
        bright = 0.5 + 0.5 * self._progress
        pulse = 0.85 + 0.15 * math.sin(self._phase * 2 * math.pi)
        # 窗体边 / 边口在带子坐标里的位置：
        # 左：窗体边在右（depth），边口在左（0）；
        # 右：窗体边在左（0），边口在右（depth）；
        # 上：窗体边在下（depth），边口在上（0）；
        # 下：窗体边在上（0），边口在下（depth）。
        # t=0 在窗体边，t=1 在边口。
        def along_coord(t: float) -> float:
            if edge in ("left", "top"):
                return depth - t * depth
            return t * depth
        center = span / 2.0
        half = span * 0.30  # 灵魂带宽 = 窗体沿边尺寸的 60%
        # ---- 灵魂带：波浪边的发光带，窗体边亮、边口淡出 ----
        path = QPainterPath()
        top_pts = []
        bot_pts = []
        steps = 16
        for s in range(steps + 1):
            t = s / steps
            coord = along_coord(t)
            # 波浪：上下边反相，带宽会轻轻起伏，像灵魂在飘。
            wave = math.sin(t * math.pi * 3 + self._phase * 2 * math.pi) * 6
            top_pts.append((coord, center - half + wave))
            bot_pts.append((coord, center + half - wave))
        if horizontal:
            path.moveTo(top_pts[0][0], top_pts[0][1])
            for x, y in top_pts[1:]:
                path.lineTo(x, y)
            for x, y in reversed(bot_pts):
                path.lineTo(x, y)
            path.closeSubpath()
            if edge == "left":
                grad = QLinearGradient(depth, 0, 0, 0)
            else:
                grad = QLinearGradient(0, 0, depth, 0)
        else:
            path.moveTo(top_pts[0][1], top_pts[0][0])
            for coord, along in top_pts[1:]:
                path.lineTo(along, coord)
            for coord, along in reversed(bot_pts):
                path.lineTo(along, coord)
            path.closeSubpath()
            if edge == "top":
                grad = QLinearGradient(0, depth, 0, 0)
            else:
                grad = QLinearGradient(0, 0, 0, depth)
        # 渐变：窗体边最亮，边口处淡到几乎透明（被口子收走）。
        grad.setColorAt(0.0, QColor(210, 240, 255, int(190 * bright * pulse)))
        grad.setColorAt(0.55, QColor(160, 210, 255, int(120 * bright * pulse)))
        grad.setColorAt(1.0, QColor(190, 235, 255, int(25 * bright)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawPath(path)
        # ---- 边口亮线：4px 柔和亮线，不是黑杠 ----
        painter.setBrush(QColor(235, 250, 255, int((170 + self._progress * 70) * pulse)))
        if edge == "left":
            painter.drawRect(0, 0, 4, h)
        elif edge == "right":
            painter.drawRect(w - 4, 0, 4, h)
        elif edge == "top":
            painter.drawRect(0, 0, w, 4)
        else:
            painter.drawRect(0, h - 4, w, 4)
        # ---- 流动光点：从窗体边漂向边口，越近边口越淡 ----
        for i in range(10):
            # 每个光点速度、相位都不同，不会整齐划一。
            dot_phase = (self._phase * (0.6 + (i % 3) * 0.2) + i * 0.13) % 1.0
            t = dot_phase  # 0 窗体边，1 边口
            coord = along_coord(t)
            # 光点在带子里的上下位置：跟随波浪，但幅度小一点。
            wave = math.sin(t * math.pi * 3 + self._phase * 2 * math.pi + i) * 5
            along = center + wave + ((i * 17) % 11 - 5)
            if horizontal:
                dx, dy = coord, along
            else:
                dx, dy = along, coord
            # 尾：向窗体边拖 3 个淡点，光点才像在流，不是一闪一闪的点。
            for k, (trail_alpha, trail_r) in enumerate(((90, 7), (55, 5), (30, 3))):
                tt = max(0.0, t - (k + 1) * 0.06)
                tcoord = along_coord(tt)
                twave = math.sin(tt * math.pi * 3 + self._phase * 2 * math.pi + i) * 5
                if horizontal:
                    tx, ty = tcoord, center + twave + ((i * 17) % 11 - 5)
                else:
                    tx, ty = center + twave + ((i * 17) % 11 - 5), tcoord
                painter.setBrush(QColor(190, 235, 255, int(trail_alpha * bright)))
                painter.drawEllipse(int(tx - trail_r // 2), int(ty - trail_r // 2), trail_r, trail_r)
            # 光点本体：越近边口越淡（被收走），不是越近越亮。
            alpha = int(230 * (1 - t * 0.55) * bright)
            size = 6 + (i % 3) * 2
            painter.setBrush(QColor(190, 235, 255, 70))
            painter.drawEllipse(int(dx - size), int(dy - size), size * 2, size * 2)
            painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawEllipse(int(dx - size // 2), int(dy - size // 2), size, size)


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
        self._drag_moved = False
        # 边缘隐藏状态：_hidden_edge 为 None = 普通悬浮窗，
        # 否则为 'left'/'right'/'top'/'bottom'，表示当前在边缘隐藏体系里；
        # _is_bar 为 True = 当前正显示小条，False = 当前是完整窗体
        # （从小条划过展开来的，鼠标离开后会变回小条）。
        self._hidden_edge = None
        self._is_bar = False
        self._bar_width = 96
        self._bar_height = 48
        self._edge_threshold = 5
        # 灵魂抽取动画：180px 内算靠近，灵魂带只在拖动完整窗体时出现。
        # 之前 90px 太小，拖得快一点就几乎看不到靠近过程，
        # 只看到贴边那一刻的形变，才会觉得“不贴上不触发”。
        self._suction_zone = 180
        self._suction_overlay = None
        self._suction_animating = False
        self._suction_timer = None
        # 吸入形变：松手后 600ms 内从完整窗体滑向边、缩小成小条，
        # 中途换内容，结束时才真正定在小条上，不再瞬间切换。
        # 之前 440ms 太赶，灵魂还没流完窗体就定型了。
        self._morph_timer = None
        self._morph_step = 0
        self._morph_total = 30
        self._morph_start = None
        self._morph_target = None
        self._morph_edge = None
        self._morph_switched = False
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
        self._card_layout = card_layout

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

        # ---- 边缘小条：隐藏后只显示剩余额度，平时不显示 ----
        # 小条就是主窗体本身变小，不是另外开一个窗口：隐藏时把
        # 额度区藏起来、只留这个标签，窗体缩到 96x48 贴在边上。
        self.bar_label = QLabel("—")
        self.bar_label.setAlignment(Qt.AlignCenter)
        bar_font = QFont()
        bar_font.setBold(True)
        bar_font.setPointSize(16)
        self.bar_label.setFont(bar_font)
        self.bar_label.setStyleSheet("color: #4ADE80;")
        self.bar_label.setVisible(False)
        card_layout.addWidget(self.bar_label, 1)

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
            self.bar_label,
        ):
            widget.installEventFilter(self)

        self._auto_login_and_load()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt 命名
        if isinstance(watched, (QPushButton, QSlider, QCheckBox)):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_moved = False
            return True
        if event.type() == QEvent.MouseMove and self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self._drag_moved = True
            if self._is_bar:
                # 小条本身在拖：只移动小条，不展开、不取消、不显示灵魂带，
                # 松手时再按离边远近决定是留在边上还是变回完整窗体。
                self._hide_suction()
                nx, ny = self._clamp_position(
                    event.globalPosition().toPoint().x() - self._drag_pos.x(),
                    event.globalPosition().toPoint().y() - self._drag_pos.y(),
                )
                self.move(nx, ny)
            else:
                # 完整窗体在拖：_drag_full_move 里做钳制 + 灵魂带，
                # 一拖动就取消隐藏，拖离边缘后松手不再自动变回小条，
                # 除非松手时又正好贴着边（松手处理里再判）。
                if self._hidden_edge is not None:
                    self._hidden_edge = None
                nx, ny = self._drag_full_move(event.globalPosition().toPoint())
                self.move(nx, ny)
            return True
        if event.type() == QEvent.MouseButtonRelease:
            self._on_drag_released()
            return True
        return super().eventFilter(watched, event)

    # ---- 齿轮与拖动 ----

    def enterEvent(self, event):  # noqa: N802
        # 小条状态下划过小条就展开成完整窗体；完整窗体下只显示齿轮。
        if self._is_bar:
            self._reveal_from_bar()
        self.gear_button.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.gear_button.setVisible(False)
        # 隐藏体系里、完整窗体状态下，鼠标离开整个窗体就变回小条。
        # 正在拖动时不变回，否则拖动中窗体一动就被藏起来。
        # 离开时灵魂带也藏起来：灵魂带只在拖动靠近时出现。
        self._hide_suction()
        if self._hidden_edge is not None and not self._is_bar and self._drag_pos is None:
            self._hide_to_bar()
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
            self._drag_moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self._drag_moved = True
            if self._is_bar:
                self._hide_suction()
                nx, ny = self._clamp_position(
                    event.globalPosition().toPoint().x() - self._drag_pos.x(),
                    event.globalPosition().toPoint().y() - self._drag_pos.y(),
                )
                self.move(nx, ny)
            else:
                if self._hidden_edge is not None:
                    self._hidden_edge = None
                nx, ny = self._drag_full_move(event.globalPosition().toPoint())
                self.move(nx, ny)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802
        # 双击不再触发隐藏：隐藏改成拖到边缘松手自动触发，
        # 这里不做任何双击处理，避免跟自动隐藏混在一起。
        self._on_drag_released()
        super().mouseReleaseEvent(event)

    # ---- 设置面板开关 ----

    def _toggle_settings(self) -> None:
        self._hide_suction()
        self._is_settings_expanded = not self._is_settings_expanded
        if self._is_settings_expanded:
            # 展开设置面板时先取消隐藏：528 宽的面板不适合变成小条，
            # 而且展开后鼠标离开再变回小条会把设置面板也藏起来。
            # 此时窗体已经是展开的状态，取消后就留在屏幕内。
            self._hidden_edge = None
            self._is_bar = False
            self.bar_label.setVisible(False)
            self.quota_widget.setVisible(True)
            self._card_layout.setContentsMargins(16, 14, 16, 12)
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
        # 展开后窗体也可能被推到屏外，钳制回屏内。
        nx, ny = self._clamp_position(self.x(), self.y(), target_width, height)
        self.move(nx, ny)
        self.gear_button.move(self.width() - 16 - 28, 14)
        diagnostics.log(
            f"settings toggled: expanded={self._is_settings_expanded} "
            f"width={self.width()} target={target_width}"
        )

    # ---- 边缘隐藏：拖不出屏 + 拖到边缘松手变小条 ----

    # ---- 多屏：之前这里只用 self.screen() 的单屏可视区钳制，
    # 双屏下窗体被钉在当前屏、拖不过屏间交界，这就是这次报的 bug。
    # 新逻辑：钳制用所有屏的虚拟外框 + 至少交叠一屏；
    # 边缘只认真实外边，屏间交界（边外一点仍在另一屏里）不算边，
    # 所以拖过交界不会触发吸入 / 隐藏，拖到某屏真正的上 / 下 /
    # 最左 / 最右外边才会触发，小条也定在窗体所在的那块屏上。

    def _available_geometries(self):
        """所有屏的 availableGeometry：排除各屏菜单栏 / Dock 的可见区。"""
        try:
            geoms = [s.availableGeometry() for s in QApplication.screens()]
        except Exception:
            geoms = []
        if not geoms:
            primary = QApplication.primaryScreen()
            if primary is not None:
                geoms = [primary.availableGeometry()]
        return geoms

    def _virtual_geometry(self):
        """所有屏的外框：左 = 最左屏的左，上 = 最上屏的上，依此类推。"""
        geoms = self._available_geometries()
        if not geoms:
            return None
        left = min(g.x() for g in geoms)
        top = min(g.y() for g in geoms)
        right = max(g.x() + g.width() for g in geoms)
        bottom = max(g.y() + g.height() for g in geoms)
        return QRect(left, top, right - left, bottom - top)

    def _screen_containing_window(self, x: int, y: int, w: int, h: int):
        """窗体中心所在的屏；中心落在屏间死角（比如高低错开的屏
        上方）时退到离中心最近的那块屏，不会返回 None。"""
        geoms = self._available_geometries()
        if not geoms:
            return None
        cx, cy = x + w // 2, y + h // 2
        for g in geoms:
            if g.contains(QPoint(cx, cy)):
                return g
        # 死角：找离中心最近的屏（矩形到点的距离，不是中心到中心，
        # 否则大屏和小屏的中心距离会误判）。
        def _dist_to_rect(g):
            dx = max(g.x() - cx, 0, cx - (g.x() + g.width()))
            dy = max(g.y() - cy, 0, cy - (g.y() + g.height()))
            return dx * dx + dy * dy

        return min(geoms, key=_dist_to_rect)

    def _screen_geometry(self):
        """窗体当前所在屏的可视区：小条 / 灵魂带 / 展开位置都按这块屏算，
        不是按虚拟外框算，否则错开的屏上小条会定在死角里看不见。"""
        geom = self._screen_containing_window(self.x(), self.y(), self.width(), self.height())
        if geom is not None:
            return geom
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()

    def _clamp_position(self, x: int, y: int, w: int = None, h: int = None):
        """钳制到虚拟外框，且窗体至少交叠一屏：

        先按虚拟外框钳制，这样双屏之间可以自由拖过去；
        钳制完若窗体跟所有屏都不交叠（比如拖进了高低错开的
        屏上方死角），再把窗体压回离它最近的那块屏里，
        不会让窗体拖到看不见的地方回不来。单屏时虚拟外框
        就是那块屏，跟以前行为完全一致。"""
        w = self.width() if w is None else w
        h = self.height() if h is None else h
        virt = self._virtual_geometry()
        if virt is None:
            return x, y
        x = max(virt.x(), min(x, virt.x() + virt.width() - w))
        y = max(virt.y(), min(y, virt.y() + virt.height() - h))
        rect = QRect(x, y, w, h)
        geoms = self._available_geometries()
        if any(g.intersects(rect) for g in geoms):
            return x, y
        # 死角：压回最近屏的可视区。
        nearest = self._screen_containing_window(x, y, w, h)
        if nearest is None:
            return x, y
        x = max(nearest.x(), min(x, nearest.x() + nearest.width() - w))
        y = max(nearest.y(), min(y, nearest.y() + nearest.height() - h))
        return x, y

    def _is_real_edge(self, edge: str, x: int, y: int, w: int, h: int, geom) -> bool:
        """这条边是不是真实外边：边外一点（窗体沿边中点处）
        若仍在任一屏里，说明是屏间交界，不是外边。"""
        if edge == "left":
            point = QPoint(x - 1, y + h // 2)
        elif edge == "right":
            point = QPoint(x + w, y + h // 2)
        elif edge == "top":
            point = QPoint(x + w // 2, y - 1)
        else:
            point = QPoint(x + w // 2, y + h)
        return not any(g.contains(point) for g in self._available_geometries())

    def _edge_at(self, x: int, y: int, w: int, h: int):
        """窗体贴着哪条真实外边（5px 内算贴着），否则返回 None。
        屏间交界即使贴着也不算，不会拖过交界就变小条。"""
        geom = self._screen_containing_window(x, y, w, h)
        if geom is None:
            return None
        candidates = []
        if abs(x - geom.x()) <= self._edge_threshold:
            candidates.append(("left", abs(x - geom.x())))
        if abs((geom.x() + geom.width()) - (x + w)) <= self._edge_threshold:
            candidates.append(("right", abs((geom.x() + geom.width()) - (x + w))))
        if abs(y - geom.y()) <= self._edge_threshold:
            candidates.append(("top", abs(y - geom.y())))
        if abs((geom.y() + geom.height()) - (y + h)) <= self._edge_threshold:
            candidates.append(("bottom", abs((geom.y() + geom.height()) - (y + h))))
        real = [(e, d) for e, d in candidates if self._is_real_edge(e, x, y, w, h, geom)]
        if not real:
            return None
        return min(real, key=lambda item: item[1])[0]

    def _nearest_edge_distance(self, x: int, y: int, w: int, h: int):
        """到最近的真实外边的距离：只算窗体所在屏的真实外边，
        屏间交界不参与，拖过交界时灵魂带不会误出。"""
        geom = self._screen_containing_window(x, y, w, h)
        if geom is None:
            return None, None
        dists = []
        for edge, dist in (
            ("left", max(0, x - geom.x())),
            ("right", max(0, (geom.x() + geom.width()) - (x + w))),
            ("top", max(0, y - geom.y())),
            ("bottom", max(0, (geom.y() + geom.height()) - (y + h))),
        ):
            if self._is_real_edge(edge, x, y, w, h, geom):
                dists.append((edge, dist))
        if not dists:
            return None, None
        return min(dists, key=lambda item: item[1])

    def _drag_full_move(self, global_point):
        """完整窗体拖动一步：钳制 + 灵魂带，返回要 move 到的位置。

        吸入动画只在拖动时算：靠近边（90px 内）就显示对应边的
        灵魂带，越近越亮；窗体不再被轻吸，窗体跟鼠标走，
        灵魂带自己从窗体边流向边口——之前轻吸 (180-距离)*0.25
        让窗体在鼠标还差 18px 时就先贴到边上，靠近过程
        被压缩到几乎看不见，才会觉得“不贴上不触发”。
        形变进行中不响应新的拖动，避免动画被打断。"""
        if self._suction_animating:
            return self.x(), self.y()
        raw_x = global_point.x() - self._drag_pos.x()
        raw_y = global_point.y() - self._drag_pos.y()
        nx, ny = self._clamp_position(raw_x, raw_y)
        if self._is_settings_expanded:
            self._hide_suction()
            return nx, ny
        edge, dist = self._nearest_edge_distance(nx, ny, self.width(), self.height())
        if edge is None or dist is None or dist > self._suction_zone:
            self._hide_suction()
            return nx, ny
        progress = 1.0 - dist / self._suction_zone
        # 不再轻吸：窗体位置就是鼠标拖到的位置（已钳制），
        # 灵魂带的长度 = 窗体到边的间隙，靠近过程完整可见。
        self._show_suction(edge, progress, nx, ny)
        return nx, ny

    def _show_suction(self, edge: str, progress: float, win_x: int, win_y: int) -> None:
        """在对应边上显示灵魂带，带子跟窗体沿边对齐、只在拖动时出现。

        带子覆盖窗体到边的间隙 + 40px 重叠进窗体边，
        重叠那一段就是窗体边在发光（灵魂正在离开身体），
        灵魂带才能从窗体里伸出来、流向边口，而不是只在边上闪。
        窗体越近间隙越短、灵魂带越短，灵魂就越接近被完全抽走。
        """
        try:
            if self._suction_overlay is None:
                self._suction_overlay = SuctionOverlay(self)
            geom = self._screen_geometry()
            if geom is None:
                return
            overlap = 40
            w, h = self.width(), self.height()
            if edge == "left":
                gap = max(0, win_x - geom.x())
                ox, oy = geom.x(), max(geom.y(), min(win_y, geom.y() + geom.height() - h))
                ow, oh = gap + overlap, h
            elif edge == "right":
                gap = max(0, (geom.x() + geom.width()) - (win_x + w))
                ox, oy = win_x + w - overlap, max(geom.y(), min(win_y, geom.y() + geom.height() - h))
                ow, oh = gap + overlap, h
            elif edge == "top":
                gap = max(0, win_y - geom.y())
                ox, oy = max(geom.x(), min(win_x, geom.x() + geom.width() - w)), geom.y()
                ow, oh = w, gap + overlap
            else:
                gap = max(0, (geom.y() + geom.height()) - (win_y + h))
                ox, oy = max(geom.x(), min(win_x, geom.x() + geom.width() - w)), win_y + h - overlap
                ow, oh = w, gap + overlap
            self._suction_overlay.show_suction(edge, ox, oy, ow, oh, progress)
        except Exception:
            # 灵魂带只是装饰，画不出来也不能影响拖动本身。
            pass

    def _hide_suction(self) -> None:
        if self._suction_overlay is not None:
            try:
                self._suction_overlay.hide_suction()
            except Exception:
                pass

    def _on_drag_released(self) -> None:
        """松手时判一次：只在真的拖动过时才判，点一下不算拖动。
        eventFilter 和 mouseReleaseEvent 都会调这里，第一次调完
        就把 _drag_moved 清掉，第二次调进来直接返回，不会重复判。"""
        moved = self._drag_moved
        self._drag_pos = None
        self._drag_moved = False
        if not moved:
            return
        if self._suction_animating:
            return
        if self._is_settings_expanded:
            self._hide_suction()
            return
        if self._is_bar:
            self._hide_suction()
            # 小条在拖：松手时还在边上就留在边上（边可能换了，
            # 比如从左边沿着上边拖到了上边），离边远了就变回完整窗体。
            edge = self._edge_at(self.x(), self.y(), self.width(), self.height())
            if edge is not None:
                self._hidden_edge = edge
                bx, by = self._bar_position(edge, self.x(), self.y())
                self.move(bx, by)
            else:
                self._cancel_bar_mode(self.x(), self.y())
            return
        # 完整窗体在拖：松手时贴着边就进灵魂形变，不贴边就直接藏起灵魂带。
        edge = self._edge_at(self.x(), self.y(), self.width(), self.height())
        if edge is not None:
            self._start_suck_in(edge)
        else:
            self._hide_suction()

    def _start_suck_in(self, edge: str) -> None:
        """松手灵魂形变：600ms 内从完整窗体滑向边、缩小成小条。

        每 20ms 走一步，位置和尺寸按 easeInOut 从完整窗体
        插值到小条位置尺寸，透明度在中途先跌到 0.2 再亮回 1.0，
        内容就在最暗的中途换成小条（藏额度区、显剩余额度标签），
        所以换内容的那一下被暗处盖住，看起来就是灵魂被抽走、
        身体变幽灵、最后在小条里重聚，而不是跳变。
        形变中灵魂带保持最亮、跟着窗体缩短，直到形变结束。
        定时器带 parent，窗体关掉时跟着没，不会在已关
        的窗体上再跑形变。"""
        if self._suction_animating:
            return
        self._suction_animating = True
        self.gear_button.setVisible(False)
        start_x, start_y = self.x(), self.y()
        start_w, start_h = self.width(), self.height()
        bar_x, bar_y = self._bar_position(edge, start_x, start_y)
        self._morph_start = (start_x, start_y, start_w, start_h)
        self._morph_target = (bar_x, bar_y, self._bar_width, self._bar_height)
        self._morph_edge = edge
        self._morph_step = 0
        self._morph_switched = False
        # 先放开固定宽度，形变才能改宽度；结束时再压回小条宽度。
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self._show_suction(edge, 1.0, start_x, start_y)
        timer = QTimer(self)
        timer.setInterval(20)
        timer.timeout.connect(self._on_morph_tick)
        self._morph_timer = timer
        timer.start()

    def _on_morph_tick(self) -> None:
        if self._morph_start is None or self._morph_target is None:
            return
        self._morph_step += 1
        total = self._morph_total
        t = min(1.0, self._morph_step / total)
        # easeInOut：中途已缩一半才换小条内容，换内容才自然。
        # 之前改成 cubic in 后，中途 t=0.5 时 eased 只有 0.125，
        # 窗体还剩 87.5% 大就换了小条内容，小条标签悬在大窗里，
        # 后半段又从 87.5% 猛缩到小条，看起来就是突然塌掉。
        eased = 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
        sx, sy, sw, sh = self._morph_start
        bx, by, bw, bh = self._morph_target
        x = int(sx + (bx - sx) * eased)
        y = int(sy + (by - sy) * eased)
        w = int(sw + (bw - sw) * eased)
        h = int(sh + (bh - sh) * eased)
        # 透明度先跌后亮：中途最暗 0.2（灵魂被抽走、身体变幽灵），
        # 换内容就藏在暗处，亮回来时已是小条。
        opacity = 1.0 - 0.8 * math.sin(math.pi * t)
        self.setWindowOpacity(opacity)
        self.setGeometry(x, y, max(20, w), max(20, h))
        # 中途换内容：不再显示额度区，改显小条标签和边距。
        # 换完不调 updateGeometry，否则布局会把窗体尺寸抢回小条，
        # 形变每步都会再把尺寸压回插值尺寸，抢回去也无所谓，
        # 但中途不调能让形变更稳。
        if t >= 0.5 and not self._morph_switched:
            self._morph_switched = True
            self.settings_widget.setVisible(False)
            self.settings_widget.setFixedWidth(0)
            self.quota_widget.setVisible(False)
            self.bar_label.setVisible(True)
            self._card_layout.setContentsMargins(8, 6, 8, 6)
            self._sync_bar_label()
        # 灵魂带跟着窗体缩短：间隙越小灵魂带越短，直到形变结束。
        if self._morph_edge is not None:
            self._show_suction(self._morph_edge, 1.0, x, y)
        if t >= 1.0:
            edge = self._morph_edge
            if self._morph_timer is not None:
                self._morph_timer.stop()
            self._morph_timer = None
            self._morph_start = None
            self._morph_target = None
            self._morph_edge = None
            self._suction_animating = False
            self.setWindowOpacity(1.0)
            self._hide_suction()
            # 真正定在小条上：内容、边距、标签都已在中途换好，
            # 万一中途没换（比如定时器被打断），这里补一次，不会再跳。
            if not self._morph_switched:
                self.settings_widget.setVisible(False)
                self.settings_widget.setFixedWidth(0)
                self.quota_widget.setVisible(False)
                self.bar_label.setVisible(True)
                self._card_layout.setContentsMargins(8, 6, 8, 6)
                self._sync_bar_label()
            self._hidden_edge = edge
            self._is_bar = True
            self.gear_button.setVisible(False)
            self.setFixedWidth(self._bar_width)
            bx2, by2 = self._bar_position(edge, x, y)
            self.resize(self._bar_width, self._bar_height)
            self.move(bx2, by2)
            self._sync_bar_label()
            diagnostics.log(f"edge hidden to bar: edge={edge} (morphed)")

    def _bar_position(self, edge: str, ref_x: int, ref_y: int):
        """小条在边上的左上角：完全在屏内，贴着边。
        左右边用原来的 y（沿边上下可拖），上下边用原来的 x。"""
        geom = self._screen_geometry()
        if geom is None:
            return ref_x, ref_y
        bw, bh = self._bar_width, self._bar_height
        if edge == "left":
            return geom.x(), max(geom.y(), min(ref_y, geom.y() + geom.height() - bh))
        if edge == "right":
            return geom.x() + geom.width() - bw, max(geom.y(), min(ref_y, geom.y() + geom.height() - bh))
        if edge == "top":
            return max(geom.x(), min(ref_x, geom.x() + geom.width() - bw)), geom.y()
        return max(geom.x(), min(ref_x, geom.x() + geom.width() - bw)), geom.y() + geom.height() - bh

    def _enter_bar_mode(self, edge: str) -> None:
        """完整窗体 -> 小条：藏起额度区、只留剩余额度标签。"""
        self._hide_suction()
        ref_x, ref_y = self.x(), self.y()
        self._hidden_edge = edge
        self._is_bar = True
        self.settings_widget.setVisible(False)
        self.settings_widget.setFixedWidth(0)
        self.quota_widget.setVisible(False)
        self.bar_label.setVisible(True)
        self.gear_button.setVisible(False)
        self._card_layout.setContentsMargins(8, 6, 8, 6)
        self.setFixedWidth(self._bar_width)
        self.updateGeometry()
        QApplication.processEvents()
        bx, by = self._bar_position(edge, ref_x, ref_y)
        self.resize(self._bar_width, self._bar_height)
        self.move(bx, by)
        self._sync_bar_label()
        diagnostics.log(f"edge hidden to bar: edge={edge}")

    def _reveal_from_bar(self) -> None:
        """小条 -> 完整窗体：仍在隐藏体系里，鼠标离开后会变回小条。"""
        if self._hidden_edge is None:
            return
        self._hide_suction()
        edge = self._hidden_edge
        bar_x, bar_y = self.x(), self.y()
        self._is_bar = False
        self.bar_label.setVisible(False)
        self.quota_widget.setVisible(True)
        self._card_layout.setContentsMargins(16, 14, 16, 12)
        self.setFixedWidth(240)
        self.updateGeometry()
        QApplication.processEvents()
        height = self.sizeHint().height()
        height = max(height, self.quota_widget.sizeHint().height() + 30)
        geom = self._screen_geometry()
        if geom is None:
            self.resize(240, height)
            return
        if edge == "left":
            x, y = geom.x(), max(geom.y(), min(bar_y, geom.y() + geom.height() - height))
        elif edge == "right":
            x, y = geom.x() + geom.width() - 240, max(geom.y(), min(bar_y, geom.y() + geom.height() - height))
        elif edge == "top":
            x, y = max(geom.x(), min(bar_x, geom.x() + geom.width() - 240)), geom.y()
        else:
            x, y = max(geom.x(), min(bar_x, geom.x() + geom.width() - 240)), geom.y() + geom.height() - height
        self.resize(240, height)
        self.move(x, y)

    def _hide_to_bar(self) -> None:
        """完整窗体（隐藏体系里）-> 小条：鼠标离开完整窗体时调。"""
        if self._hidden_edge is None:
            return
        self._enter_bar_mode(self._hidden_edge)

    def _cancel_bar_mode(self, x: int, y: int) -> None:
        """小条 -> 普通完整窗体：拖离边缘后取消隐藏，不再自动变回小条。"""
        self._hide_suction()
        self._hidden_edge = None
        self._is_bar = False
        self.bar_label.setVisible(False)
        self.quota_widget.setVisible(True)
        self._card_layout.setContentsMargins(16, 14, 16, 12)
        self.setFixedWidth(240)
        self.updateGeometry()
        QApplication.processEvents()
        height = self.sizeHint().height()
        height = max(height, self.quota_widget.sizeHint().height() + 30)
        nx, ny = self._clamp_position(x, y, 240, height)
        self.resize(240, height)
        self.move(nx, ny)

    def _sync_bar_label(self) -> None:
        """小条里的剩余额度跟主窗同步，颜色也跟主窗一致。"""
        if self._last_good is not None:
            remaining = max(0.0, min(100.0, self._last_good.remaining))
            self.bar_label.setText(f"{remaining:.0f}%")
            self.bar_label.setStyleSheet(f"color: {_remaining_color(remaining)};")
        else:
            self.bar_label.setText("—")
            self.bar_label.setStyleSheet("color: #4ADE80;")

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
        # 小条状态下额度刷新只改小条里的数字和颜色，窗体保持小条尺寸，
        # 不会因为节奏区出现/消失就把小条撑回完整窗体。
        self._sync_bar_label()

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
