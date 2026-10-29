"""悬浮窗本体：无边框、圆角、默认始终置顶，可拖动。

正常时只显示额度：剩余百分比大字 + 主条 + 节奏刻度 + 重置时间，
不显示标题、计划、已用、额外词元等字样。
没有右键菜单：右上角齿轮按钮只在鼠标悬停时显示，平时不显示；
点齿轮后窗体改为上下结构：上方只留剩余额度百分比及进度条，
下方是设置（无明显边框，上下中间只有一条不到边的细线隔开），
再点齿轮可收回。设置展开/收起的过渡跟边缘隐藏缩小形变同款：
600ms、easeInOut、透明度先跌到 0.2 再亮回 1.0，中途换内容。

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

边缘动画已删（2026-10-23 Ren 定）：拖动靠近边时不再显示
任何边带、光丝、传送门效果，只有松手贴边时才进缩小形变。
松手贴边后不再瞬间切小条，而是 600ms 形变过渡：窗体
按 easeInOut 滑向边、缩小、透明度先跌到 0.2 再亮回 1.0，
中途在最暗处换成小条内容，最后定在小条上。
双屏屏间交界不算边，拖过交界不会变小条。

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
        # Qt.Tool：工具窗在 Windows 上不进任务栏、不进托盘、不进 Alt-Tab，
        # 启动时就不会在底部出现那个带绿 % 的图标；退出只走设置面板里
        # 的“退出软件”按钮（调 QApplication.quit()，不能只调 self.close()：
        # Tool 窗默认没有 WA_QuitOnClose，close() 只关窗口不退进程，
        # 进程无窗口残留、还占着 dist 里的 qwindows.dll，PyInstaller
        # --clean 删 dist 时就会报 WinError 5 拒绝访问）。无边框 + 始终置顶不变。
        # 注意：main.py 里那个“任务栏显示图标”的注释已过时，
        # 加 Tool 后任务栏不再显示它，图标只剩窗口自身的装饰（无边框故不可见）。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
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
        self._suction_animating = False
        self._suction_timer = None
        # 缩小形变：松手贴边后 600ms 内从完整窗体滑向边、缩小成小条，
        # 中途换内容，结束时才真正定在小条上，不再瞬间切换。
        self._morph_timer = None
        self._morph_step = 0
        self._morph_total = 30
        self._morph_start = None
        self._morph_target = None
        self._morph_edge = None
        self._morph_switched = False
        # 缩小形变是谁触发的：drag = 拖动松手贴边，leave = 鼠标离开完整窗体。
        # 区分它是为了形变结束时决定要不要自动再展开：
        # leave 触发且形变结束时鼠标又回到小条上，才自动再展开；
        # drag 触发时鼠标本来就在小条上，绝不能自动再展开，
        # 否则拖过去隐藏会立刻又弹回完整窗体。
        self._morph_trigger = "drag"
        # 上一次完整窗体的高度：小条展开形变的目标高度就用它，
        # 因为小条宽度 96 时量不出 240 宽时的正确高度；
        # 进小条时记下，展开时直接用它，结束时再按实际内容定型一次。
        self._last_full_height = None
        # 展开形变（小条 -> 中等窗）：跟缩小形变同款参数、反向，
        # 600ms、30 步、easeInOut、透明度先跌到 0.2 再亮回 1.0，
        # 中途换内容，结束时才真正定在中等窗上，不再直接弹开。
        self._reveal_morph_timer = None
        self._reveal_morph_step = 0
        self._reveal_morph_total = 30
        self._reveal_morph_start = None
        self._reveal_morph_target = None
        self._reveal_morph_edge = None
        self._reveal_morph_switched = False
        self._reveal_morphing = False
        # 设置展开/收起形变：跟边缘隐藏缩小同款，600ms、30 步、
        # easeInOut、透明度先跌到 0.2 再亮回 1.0，中途换内容。
        self._settings_morph_timer = None
        self._settings_morph_step = 0
        self._settings_morph_total = 30
        self._settings_morph_start = None
        self._settings_morph_target = None
        self._settings_morph_expanding = False
        self._settings_morph_switched = False
        self._settings_morphing = False
        self._settings_morph_fixed_h = None
        # 设置从小条展开而来时记下的原隐藏边：小条划过展开成完整窗体
        # （_hidden_edge 仍在）再点齿轮展开设置，记下这条边；
        # 收起设置时若它还在，就直接回到小条，而不是停在完整窗体。
        # 不是从小条来的（正常完整窗体点齿轮）时它是 None，收起就回完整窗体。
        self._settings_return_edge = None
        # 本次设置形变是不是直接到小条（收起 + 原来是小条来的）。
        self._settings_morph_to_bar = False
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

        card_layout = QVBoxLayout(card)
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
        # 节奏文案改成日期时间后变长了（“快 10% · 预计 10-26 12:51 用完”
        # 共 25 字），12pt 在 240 宽窗体里（卡片内宽 208px）会把
        # 最后一个“完”字裁出界；改成 10pt，宽度约等于原来
        # “提前 X 天”文案在 12pt 的宽度，刚好能放进一行。
        # 再加 wordWrap 兜底：Windows 字体稍宽时即使 10pt 仍超长，
        # 宁可换成两行，也不要把字裁掉。
        pace_font = QFont()
        pace_font.setBold(True)
        pace_font.setPointSize(10)
        self.pace_label.setFont(pace_font)
        self.pace_label.setWordWrap(True)
        pace_layout.addWidget(self.pace_label)
        self.pace_widget.setVisible(False)
        quota_layout.addWidget(self.pace_widget)

        self.time_label = QLabel("未登录")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        quota_layout.addWidget(self.time_label)

        card_layout.addWidget(self.quota_widget, 0)

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
        card_layout.addWidget(self.bar_label, 0)

        # ---- 上下中间的细线：不到边，左右各留 24px ----
        # 细线本身是 QFrame，包在一个带左右边距的容器里才不到边；
        # 平时隐藏，设置展开时才显示。
        self._divider_widget = QWidget()
        divider_layout = QHBoxLayout(self._divider_widget)
        divider_layout.setContentsMargins(24, 10, 24, 10)
        divider_layout.setSpacing(0)
        divider_line = QFrame()
        divider_line.setFrameShape(QFrame.HLine)
        divider_line.setFixedHeight(1)
        divider_line.setStyleSheet("background-color: #606060; border: none;")
        divider_layout.addWidget(divider_line)
        self._divider_widget.setVisible(False)
        card_layout.addWidget(self._divider_widget, 0)

        # ---- 设置面板：上下结构，无明显边框 ----
        # 不再是右侧 300 宽的卡片：背景透明、无边框、无圆角，
        # 宽度跟窗体走（240 宽减去卡片边距），只靠上面那条细线隔开。
        self.settings_widget = QWidget()
        self.settings_widget.setObjectName("settingsCard")
        self.settings_widget.setStyleSheet("QWidget#settingsCard { background-color: transparent; border: none; }")
        self.settings_widget.setVisible(False)
        settings_layout = QVBoxLayout(self.settings_widget)
        settings_layout.setContentsMargins(0, 4, 0, 0)
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
        # 账号信息暂时不显示（2026-10-23 Ren 定：获取不到就先不显示）：
        # 标签建出来但始终隐藏，登录状态只靠下面登录/退出按钮二选一
        # 来表示（只显登录 = 未登录，只显退出 = 已登录），不写
        # “当前账号：…”也不写“未登录”。以后要恢复时，把
        # _update_login_status 里那句 setVisible(False) 拿掉即可，
        # 取账号的逻辑（session.account）还留着没删。
        self.login_status_label = QLabel("未登录")
        self.login_status_label.setWordWrap(True)
        self.login_status_label.setVisible(False)
        self.login_status_label.setStyleSheet(f"color: {SECONDARY_TEXT}; font-size: 13px;")
        settings_layout.addWidget(self.login_status_label)
        spacer(8)
        # 登录 / 退出只显示其中一个（见 _update_login_status）：
        # 未登录时只显登录，已登录时只显退出，两个按钮都放在
        # 同一行布局里，隐藏的那个不占地方，显示的那个占满整行。
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

        # 删掉的控件（Ren 要求）：始终置顶、打开诊断日志、完成。
        # 始终置顶删掉后窗体默认始终置顶（初始化时已设 StaysOnTopHint，
        # 不再提供关掉它的开关）；完成删掉后收起设置只靠再点一次齿轮；
        # 退出软件保留，否则无边框窗体没法正常退出。
        spacer(16)
        exit_button = QPushButton("退出软件")
        exit_button.setStyleSheet(DANGER_BUTTON_STYLE)
        exit_button.clicked.connect(self._on_exit_clicked)
        settings_layout.addWidget(exit_button)

        card_layout.addWidget(self.settings_widget, 0)
        card_layout.setSpacing(0)

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
                # 小条本身在拖：只移动小条，不展开、不取消。
                # 松手时再按离边远近决定是留在边上还是变回完整窗体。
                nx, ny = self._clamp_position(
                    event.globalPosition().toPoint().x() - self._drag_pos.x(),
                    event.globalPosition().toPoint().y() - self._drag_pos.y(),
                )
                self.move(nx, ny)
            else:
                # 完整窗体在拖：_drag_full_move 里只做钳制。
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
        # 小条状态下划过小条就展开：不再直接弹开，走跟缩小形变同款、
        # 反向的 600ms 展开形变（位置/尺寸插值、透明度跌到 0.2 再亮回、
        # 中途换中等窗内容）。形变进行中不重复触发，齿轮在形变结束
        # 时才显示，形变中途不提前露出来。
        if self._is_bar:
            if not self._suction_animating and not self._settings_morphing and not self._reveal_morphing:
                self._start_reveal_morph(self._hidden_edge)
            super().enterEvent(event)
            return
        self.gear_button.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.gear_button.setVisible(False)
        # 隐藏体系里、完整窗体状态下，鼠标离开整个窗体就变回小条，
        # 也不再直接弹回：走跟拖动隐藏相同的缩小形变。
        # 正在拖动时不变回，否则拖动中窗体一动就被藏起来；
        # 形变进行中不重复触发，展开形变结束时会自己判鼠标还在不在，
        # 不在就自动再进缩小形变，不用这里抢。
        if self._suction_animating or self._settings_morphing or self._reveal_morphing:
            super().leaveEvent(event)
            return
        if self._hidden_edge is not None and not self._is_bar and self._drag_pos is None:
            self._start_suck_in(self._hidden_edge, trigger="leave")
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

    def _apply_settings_content(self, expanded: bool) -> None:
        """只换设置展开/收起时的内容，不动窗体尺寸（形变中途调它）。

        expanded=True：上方只留百分比和进度条，节奏和重置时间隐藏，
        细线和设置块显示，登录状态按当前账号刷新；
        expanded=False：上方恢复完整（百分比、进度条、节奏、重置时间），
        细线和设置块隐藏。卡片边距两边都是 16,14,16,12。
        """
        self._is_settings_expanded = expanded
        if expanded:
            self._hidden_edge = None
            self._is_bar = False
            self.bar_label.setVisible(False)
            self.quota_widget.setVisible(True)
            self._set_quota_mini(True)
            self._divider_widget.setVisible(True)
            self.settings_widget.setVisible(True)
            self._update_login_status()
        else:
            self._divider_widget.setVisible(False)
            self.settings_widget.setVisible(False)
            self.quota_widget.setVisible(True)
            self.bar_label.setVisible(False)
            self._set_quota_mini(False)
            # 收起后节奏要不要显示由数据决定：有快照时 _show 会再调
            # _show_pace，这里先按上次快照恢复一次，免得收起后节奏区空着。
            if self._last_good is not None:
                self._show_pace(self._last_good, max(0.0, min(100.0, self._last_good.remaining)))
        self._card_layout.setContentsMargins(16, 14, 16, 12)

    def _measure_settings_height(self, expanded: bool) -> int:
        """在当前内容状态下量一次窗体高度（不改动最终状态、不闪屏）。

        先把内容切到目标状态、量 sizeHint，再切回原状态。
        以前这里调了两次 processEvents，Qt 会在量高度之前先把
        目标内容重绘一遍：点齿轮后窗体先闪一下目标内容（被旧尺寸
        夹着）、再闪回原内容、形变才开始，看起来就是卡顿。
        现在量的时候把整窗的 updates 关掉、不调 processEvents，
        只算 sizeHint，算完切回原状态再开 updates，重绘时只看到
        原内容，形变从原尺寸平滑过去。量的时候把
        _settings_morphing 置 True，免得 _show_pace 里的
        adjustSize 在量之前就把窗体先缩/放到目标高度。
        """
        prev = self._is_settings_expanded
        self._settings_morphing = True
        self.setUpdatesEnabled(False)
        try:
            self._apply_settings_content(expanded)
            self.updateGeometry()
            height = self.sizeHint().height()
            height = max(height, self.quota_widget.sizeHint().height() + 30)
        finally:
            self._settings_morphing = False
        # 切回原状态，形变从原尺寸开始。
        self._apply_settings_content(prev)
        self.updateGeometry()
        self.setUpdatesEnabled(True)
        return height

    def _toggle_settings(self) -> None:
        """点齿轮展开/收起设置：展开用真抽屉，收起保持原样。

        收起（隐藏）已经不错，不动它：开始前先换成中等窗内容，
        再从大窗高度缩到中等高度，中等内容始终够高、不压扁，
        下面空白逐渐缩没，结束时不再换内容。
        展开上一版的问题是最后弹一下：先长高（下面是空白卡片）、
        到结束时才换成设置内容，设置是突然出现的，不是长出来的。
        真抽屉的做法是展开时开始前就换成设置内容、再长高，
        但上一版抽屉失败的原因是布局会把高度不够的设置压扁。
        这次补上关键一步：形变期间把设置高度固定住（固定高度 =
        展开后的完整高度），布局就压不动它，窗体高度不够时
        只会裁掉设置的下半部分、不会把它压扁，设置是随着
        窗体长高从上到下露出来的，到结束时刚好全露出来，
        结束时再放开固定高度。收起到小条是例外：高度要缩到 48，
        任何内容都不够高，仍走旧的透明度跌亮 + 中途换小条内容。
        透明度全程 1.0 不变，形变中途不换内容（小条除外）。
        宽度始终 240，只有高度在变。形变进行中再点齿轮直接返回。
        """
        if self._settings_morphing or self._suction_animating or self._reveal_morphing:
            return
        expanding = not self._is_settings_expanded
        start_x, start_y = self.x(), self.y()
        start_w, start_h = self.width(), self.height()
        # 展开时记下原隐藏边：小条划过展开成完整窗体时 _hidden_edge 还在，
        # 点齿轮展开设置前先记下来，收起时才能回到小条；
        # 正常完整窗体点齿轮时 _hidden_edge 是 None，记下来就是 None，
        # 收起时回完整窗体。收起时不覆盖它，用展开时记下的那条边。
        if expanding:
            self._settings_return_edge = self._hidden_edge
        to_bar = (not expanding) and (self._settings_return_edge is not None)
        if to_bar:
            # 收起 + 原来是小条来的：形变目标直接是小条，不是完整窗体，
            # 一次形变就从大窗回到小条，不用先回完整窗体再二次缩小。
            # 先量一次完整高度存起来，供以后小条展开当目标高度用，
            # 否则展开会误用展开后的大窗高度。
            try:
                self._last_full_height = self._measure_settings_height(False)
            except Exception:
                pass
            bar_x, bar_y = self._bar_position(self._settings_return_edge, start_x, start_y)
            target_x, target_y, target_w, target_h = bar_x, bar_y, self._bar_width, self._bar_height
        else:
            # 目标高度：先量目标状态的高度，再切回当前状态开始形变。
            target_h = self._measure_settings_height(expanding)
            target_w = 240
            # 目标位置：宽度不变，高度变后若超出屏底就往上挪，
            # 保证展开后的大窗完整在屏内，形变时位置也平滑过去。
            geom = self._screen_geometry()
            target_x, target_y = start_x, start_y
            if geom is not None:
                target_x = max(geom.x(), min(start_x, geom.x() + geom.width() - target_w))
                if target_h <= geom.height():
                    target_y = max(geom.y(), min(start_y, geom.y() + geom.height() - target_h))
                else:
                    target_y = geom.y()
        self._settings_morphing = True
        self._settings_morph_expanding = expanding
        self._settings_morph_to_bar = to_bar
        self._settings_morph_start = (start_x, start_y, start_w, start_h)
        self._settings_morph_target = (target_x, target_y, target_w, target_h)
        self._settings_morph_step = 0
        # 换内容时机：
        # 展开时开始前就换成设置内容（真抽屉），并把设置高度固定住，
        # 布局压不动它，窗体只裁下半部分；收起回中等窗时开始前就
        # 换成中等窗内容（原样，不动）；收起到小条时开始前不换，
        # 形变中途（旧逻辑）才换小条。
        # 所以展开和收起回中等窗时 switched 都置 True（已换），
        # 只有收起到小条时 switched 保持 False、中途才换。
        self._settings_morph_switched = not to_bar
        if self._settings_morph_switched:
            self._apply_settings_content(expanding)
            if expanding:
                # 固定设置高度：布局给设置分配高度时不能把它压扁，
                # 窗体高度不够的部分由卡片裁掉，设置从上到下露出来。
                # 高度取展开后设置本身的 sizeHint，宽度不动。
                self.updateGeometry()
                self._settings_morph_fixed_h = self.settings_widget.sizeHint().height()
                self.settings_widget.setFixedHeight(self._settings_morph_fixed_h)
            else:
                self._settings_morph_fixed_h = None
        # 形变期间固定尺寸，布局的 sizeHint 才不会把窗体抢回内容高度；
        # 结束时再放开高度、只固定宽度 240。
        self.setFixedSize(start_w, start_h)
        timer = QTimer(self)
        timer.setInterval(20)
        timer.timeout.connect(self._on_settings_morph_tick)
        self._settings_morph_timer = timer
        timer.start()

    def _on_settings_morph_tick(self) -> None:
        if self._settings_morph_start is None or self._settings_morph_target is None:
            return
        self._settings_morph_step += 1
        total = self._settings_morph_total
        t = min(1.0, self._settings_morph_step / total)
        # 非小条路径：easeInOut 只变高度/位置，透明度全程 1.0，
        # 形变中途不换内容（展开和收起都已在开始前换好）。
        # 展开时设置高度已固定，布局压不动它，窗体只裁下半部分；
        # 收起时设置已隐藏，中等内容始终够高。
        # 小条路径例外：高度要缩到 48，任何内容都不够高，
        # 仍用旧的透明度跌亮 + 中途换小条内容，靠暗处盖住压扁。
        eased = 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
        sx, sy, sw, sh = self._settings_morph_start
        bx, by, bw, bh = self._settings_morph_target
        x = int(sx + (bx - sx) * eased)
        y = int(sy + (by - sy) * eased)
        w = int(sw + (bw - sw) * eased)
        h = int(sh + (bh - sh) * eased)
        if self._settings_morph_to_bar:
            self.setWindowOpacity(1.0 - 0.8 * math.sin(math.pi * t))
        self.setFixedSize(max(20, w), max(20, h))
        self.move(x, y)
        if t >= 0.5 and not self._settings_morph_switched and self._settings_morph_to_bar:
            self._settings_morph_switched = True
            self._is_settings_expanded = False
            self._divider_widget.setVisible(False)
            self.settings_widget.setVisible(False)
            self._set_quota_mini(False)
            self.quota_widget.setVisible(False)
            self.bar_label.setVisible(True)
            self._card_layout.setContentsMargins(8, 6, 8, 6)
            self._sync_bar_label()
        if t >= 1.0:
            expanding = self._settings_morph_expanding
            to_bar = self._settings_morph_to_bar
            return_edge = self._settings_return_edge
            if self._settings_morph_timer is not None:
                self._settings_morph_timer.stop()
            self._settings_morph_timer = None
            self._settings_morph_start = None
            self._settings_morph_target = None
            self._settings_morphing = False
            self._settings_morph_to_bar = False
            self.setWindowOpacity(1.0)
            if to_bar:
                # 直接到小条定型：跟边缘隐藏缩小同款定型，
                # 万一中途没换，这里补一次，不会再跳。
                if not self._settings_morph_switched:
                    self._is_settings_expanded = False
                    self._divider_widget.setVisible(False)
                    self.settings_widget.setVisible(False)
                    self._set_quota_mini(False)
                    self.quota_widget.setVisible(False)
                    self.bar_label.setVisible(True)
                    self._card_layout.setContentsMargins(8, 6, 8, 6)
                    self._sync_bar_label()
                self._hidden_edge = return_edge
                self._is_bar = True
                self._settings_return_edge = None
                self.gear_button.setVisible(False)
                self.setMinimumWidth(0)
                self.setMaximumWidth(16777215)
                self.setMinimumHeight(0)
                self.setMaximumHeight(16777215)
                self.setFixedWidth(self._bar_width)
                bx2, by2 = self._bar_position(return_edge, x, y) if return_edge is not None else (x, y)
                self.resize(self._bar_width, self._bar_height)
                self.move(bx2, by2)
                self._sync_bar_label()
                diagnostics.log(f"settings toggled: expanded=False to bar edge={return_edge}")
                return
            if not self._settings_morph_switched:
                # 只有收起到小条以外的路径走到这里时才可能没换，
                # 补一次，免得结束时内容还停在旧状态。
                self._settings_morphing = True
                try:
                    self._apply_settings_content(expanding)
                finally:
                    self._settings_morphing = False
                self._settings_morph_switched = True
            # 结束时放开设置固定高度：展开时固定住是为了不被压扁，
            # 高度已到目标、设置已全露，放开后布局高度就是完整高度，
            # 不会再跳；收起时本来就没固定，这里是空操作。
            if self._settings_morph_fixed_h is not None:
                self.settings_widget.setMinimumHeight(0)
                self.settings_widget.setMaximumHeight(16777215)
                self._settings_morph_fixed_h = None
            # 结束时放开高度、只固定宽度 240，定在目标尺寸和位置。
            # 定型高度优先用形变目标高度（量高度时已算好），不再
            # 在这里调 processEvents 重算一次，否则结束那一下会
            # 再闪一次、看起来像卡顿的第二跳；只有实际内容高度
            # 跟目标差 2px 以上时才用实际高度，免得内容被夹。
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setFixedWidth(240)
            self.updateGeometry()
            # morph_target 已在上面清掉，这里用本步插值终点 h，
            # t=1.0 时它就是目标高度，不用再从已清掉的变量里取。
            target_h = h
            final_h = self.sizeHint().height()
            final_h = max(final_h, self.quota_widget.sizeHint().height() + 30)
            if abs(final_h - target_h) <= 2:
                final_h = target_h
            # 位置按屏内钳制，避免定型后超出屏底。
            nx, ny = self._clamp_position(self.x(), self.y(), 240, final_h)
            self.resize(240, final_h)
            self.move(nx, ny)
            self.gear_button.move(self.width() - 16 - 28, 14)
            diagnostics.log(
                f"settings toggled: expanded={self._is_settings_expanded} "
                f"width={self.width()} height={self.height()}"
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
        """窗体当前所在屏的可视区：小条 / 展开位置都按这块屏算，
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

    def _drag_full_move(self, global_point):
        """完整窗体拖动一步：只钳制，返回要 move 到的位置。

        边缘动画已按 Ren 要求删掉：拖动时不再显示任何边带，
        只有松手贴边时才进下面的缩小形变过渡。
        形变进行中不响应新的拖动，避免形变被打断。"""
        if self._suction_animating or self._settings_morphing or self._reveal_morphing:
            return self.x(), self.y()
        raw_x = global_point.x() - self._drag_pos.x()
        raw_y = global_point.y() - self._drag_pos.y()
        nx, ny = self._clamp_position(raw_x, raw_y)
        return nx, ny

    def _on_drag_released(self) -> None:
        """松手时判一次：只在真的拖动过时才判，点一下不算拖动。
        eventFilter 和 mouseReleaseEvent 都会调这里，第一次调完
        就把 _drag_moved 清掉，第二次调进来直接返回，不会重复判。"""
        moved = self._drag_moved
        self._drag_pos = None
        self._drag_moved = False
        if not moved:
            return
        if self._suction_animating or self._settings_morphing or self._reveal_morphing:
            return
        if self._is_settings_expanded:
            # 设置展开时拖动也要能隐藏：拖到边缘松手就进缩小形变，
            # 形变中途会藏掉设置块和细线、定在小条上；
            # 没拖到边缘就什么都不做，设置保持展开，不会因为松手就收起。
            edge = self._edge_at(self.x(), self.y(), self.width(), self.height())
            if edge is not None:
                self._settings_return_edge = None
                self._start_suck_in(edge)
            return
        if self._is_bar:
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
        # 完整窗体在拖：松手时贴着边就进缩小形变，不贴边就什么都不做。
        edge = self._edge_at(self.x(), self.y(), self.width(), self.height())
        if edge is not None:
            self._start_suck_in(edge)

    def _start_suck_in(self, edge: str, trigger: str = "drag") -> None:
        """松手缩小形变：600ms 内从完整窗体滑向边、缩小成小条。

        每 20ms 走一步，位置和尺寸按 easeInOut 从完整窗体
        插值到小条位置尺寸，透明度在中途先跌到 0.2 再亮回 1.0，
        内容就在最暗的中途换成小条（藏额度区、显剩余额度标签），
        所以换内容的那一下被暗处盖住，看起来就是窗体
        被边吸着变形、最后定成小条，而不是跳变。
        定时器带 parent，窗体关掉时跟着没，不会在已关
        的窗体上再跑形变。"""
        if self._suction_animating or self._reveal_morphing or self._settings_morphing:
            return
        self._suction_animating = True
        self._morph_trigger = trigger
        self.gear_button.setVisible(False)
        start_x, start_y = self.x(), self.y()
        start_w, start_h = self.width(), self.height()
        if self._is_settings_expanded:
            try:
                self._last_full_height = self._measure_settings_height(False)
            except Exception:
                pass
        else:
            self._last_full_height = start_h
        bar_x, bar_y = self._bar_position(edge, start_x, start_y)
        self._morph_start = (start_x, start_y, start_w, start_h)
        self._morph_target = (bar_x, bar_y, self._bar_width, self._bar_height)
        self._morph_edge = edge
        self._morph_step = 0
        self._morph_switched = False
        # 先放开固定宽度，形变才能改宽度；结束时再压回小条宽度。
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
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
        # 透明度先跌后亮：中途最暗 0.2（先暗后亮），
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
            # 进小条清设置展开标志，同 _enter_bar_mode 的原因：
            # 否则设置展开时拖到边缘进小条，标志留着 True，
            # 刷新和展开都会把节奏藏起来，漏出第四种状态。
            self._is_settings_expanded = False
            self.settings_widget.setVisible(False)
            self._divider_widget.setVisible(False)
            self._set_quota_mini(False)
            self.quota_widget.setVisible(False)
            self.bar_label.setVisible(True)
            self._card_layout.setContentsMargins(8, 6, 8, 6)
            self._sync_bar_label()
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
            # 真正定在小条上：内容、边距、标签都已在中途换好，
            # 万一中途没换（比如定时器被打断），这里补一次，不会再跳。
            if not self._morph_switched:
                self._is_settings_expanded = False
                self.settings_widget.setVisible(False)
                self._divider_widget.setVisible(False)
                self._set_quota_mini(False)
                self.quota_widget.setVisible(False)
                self.bar_label.setVisible(True)
                self._card_layout.setContentsMargins(8, 6, 8, 6)
                self._sync_bar_label()
            self._hidden_edge = edge
            self._is_bar = True
            self._is_settings_expanded = False
            self.gear_button.setVisible(False)
            self.setFixedWidth(self._bar_width)
            bx2, by2 = self._bar_position(edge, x, y)
            self.resize(self._bar_width, self._bar_height)
            self.move(bx2, by2)
            self._sync_bar_label()
            diagnostics.log(f"edge hidden to bar: edge={edge} (morphed)")
            if self._morph_trigger == "leave":
                try:
                    from PySide6.QtGui import QCursor as _QCursor

                    if self.geometry().contains(_QCursor.pos()):
                        self._start_reveal_morph(edge)
                except Exception:
                    pass

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
        """完整窗体 -> 小条：藏起额度区、只留剩余额度标签。

        进小条必清设置展开标志：设置展开时拖到边缘进小条，
        若标志还留着 True，下次刷新 _show_pace 会以为还在设置展开、
        把节奏藏起来，小条划过展开后就只剩 % + 条、无节奏/重置、
        也无设置块，成了第四种状态。清掉后小条展开必回中等窗。
        """
        ref_x, ref_y = self.x(), self.y()
        self._last_full_height = self.height()
        self._hidden_edge = edge
        self._is_bar = True
        self._is_settings_expanded = False
        self.settings_widget.setVisible(False)
        self._divider_widget.setVisible(False)
        self._set_quota_mini(False)
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
        """小条 -> 中等窗：只做形变入口，真正展开走 _start_reveal_morph。

        仍在隐藏体系里，鼠标离开后会变回小条（离开时走缩小形变）。
        """
        if self._hidden_edge is None:
            return
        self._start_reveal_morph(self._hidden_edge)

    def _start_reveal_morph(self, edge: str) -> None:
        """展开形变：小条 -> 中等窗，缩小形变的反向、同款动画。

        600ms、30 步、easeInOut、透明度先跌到 0.2 再亮回 1.0，
        中途在最暗处换成中等窗内容（藏小条标签、显额度区、
        顶块回完整 % + 条 + 节奏 + 重置时间），而不是直接弹开。
        目标高度用进小条时记下的完整高度（小条宽度下量不准），
        结束时再按实际内容定型一次、钳制回屏内。
        形变结束时若鼠标已不在窗内，自动再进缩小形变，
        不用用户先移出再移入才触发离开隐藏。
        """
        if edge is None:
            return
        if self._reveal_morphing or self._suction_animating or self._settings_morphing:
            return
        if not self._is_bar:
            return
        start_x, start_y = self.x(), self.y()
        start_w, start_h = self.width(), self.height()
        height = self._last_full_height or 180
        height = max(100, min(600, int(height)))
        geom = self._screen_geometry()
        if geom is None:
            target_x, target_y = start_x, start_y
        elif edge == "left":
            target_x, target_y = geom.x(), max(geom.y(), min(start_y, geom.y() + geom.height() - height))
        elif edge == "right":
            target_x, target_y = geom.x() + geom.width() - 240, max(geom.y(), min(start_y, geom.y() + geom.height() - height))
        elif edge == "top":
            target_x, target_y = max(geom.x(), min(start_x, geom.x() + geom.width() - 240)), geom.y()
        else:
            target_x, target_y = max(geom.x(), min(start_x, geom.x() + geom.width() - 240)), geom.y() + geom.height() - height
        self._reveal_morphing = True
        self._reveal_morph_edge = edge
        self._reveal_morph_start = (start_x, start_y, start_w, start_h)
        self._reveal_morph_target = (target_x, target_y, 240, height)
        self._reveal_morph_step = 0
        self._reveal_morph_switched = False
        self.gear_button.setVisible(False)
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setFixedSize(start_w, start_h)
        timer = QTimer(self)
        timer.setInterval(20)
        timer.timeout.connect(self._on_reveal_morph_tick)
        self._reveal_morph_timer = timer
        timer.start()

    def _on_reveal_morph_tick(self) -> None:
        if self._reveal_morph_start is None or self._reveal_morph_target is None:
            return
        self._reveal_morph_step += 1
        total = self._reveal_morph_total
        t = min(1.0, self._reveal_morph_step / total)
        eased = 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
        sx, sy, sw, sh = self._reveal_morph_start
        bx, by, bw, bh = self._reveal_morph_target
        x = int(sx + (bx - sx) * eased)
        y = int(sy + (by - sy) * eased)
        w = int(sw + (bw - sw) * eased)
        h = int(sh + (bh - sh) * eased)
        opacity = 1.0 - 0.8 * math.sin(math.pi * t)
        self.setWindowOpacity(opacity)
        self.setFixedSize(max(20, w), max(20, h))
        self.move(x, y)
        if t >= 0.5 and not self._reveal_morph_switched:
            self._reveal_morph_switched = True
            self._is_bar = False
            self._is_settings_expanded = False
            self.bar_label.setVisible(False)
            self.settings_widget.setVisible(False)
            self._divider_widget.setVisible(False)
            self.quota_widget.setVisible(True)
            self._set_quota_mini(False)
            if self._last_good is not None:
                self._show_pace(self._last_good, max(0.0, min(100.0, self._last_good.remaining)))
            self._card_layout.setContentsMargins(16, 14, 16, 12)
        if t >= 1.0:
            edge = self._reveal_morph_edge
            if self._reveal_morph_timer is not None:
                self._reveal_morph_timer.stop()
            self._reveal_morph_timer = None
            self._reveal_morph_start = None
            self._reveal_morph_target = None
            self._reveal_morph_edge = None
            self._reveal_morphing = False
            self.setWindowOpacity(1.0)
            if not self._reveal_morph_switched:
                self._is_bar = False
                self._is_settings_expanded = False
                self.bar_label.setVisible(False)
                self.settings_widget.setVisible(False)
                self._divider_widget.setVisible(False)
                self.quota_widget.setVisible(True)
                self._set_quota_mini(False)
                if self._last_good is not None:
                    self._show_pace(self._last_good, max(0.0, min(100.0, self._last_good.remaining)))
                self._card_layout.setContentsMargins(16, 14, 16, 12)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setFixedWidth(240)
            self.updateGeometry()
            QApplication.processEvents()
            final_h = self.sizeHint().height()
            final_h = max(final_h, self.quota_widget.sizeHint().height() + 30)
            nx, ny = self._clamp_position(self.x(), self.y(), 240, final_h)
            self.resize(240, final_h)
            self.move(nx, ny)
            self._last_full_height = final_h
            self.gear_button.setVisible(True)
            self.gear_button.move(self.width() - 16 - 28, 14)
            diagnostics.log(f"bar revealed: edge={edge} (morphed)")
            try:
                from PySide6.QtGui import QCursor as _QCursor

                if not self.geometry().contains(_QCursor.pos()):
                    if self._hidden_edge is not None and self._drag_pos is None:
                        self._start_suck_in(self._hidden_edge, trigger="leave")
            except Exception:
                pass

    def _hide_to_bar(self) -> None:
        """完整窗体（隐藏体系里）-> 小条：走缩小形变，不再直接切换。"""
        if self._hidden_edge is None:
            return
        self._start_suck_in(self._hidden_edge, trigger="leave")

    def _cancel_bar_mode(self, x: int, y: int) -> None:
        """小条 -> 普通中等窗：拖离边缘后取消隐藏，不再自动变回小条。"""
        self._hidden_edge = None
        self._is_bar = False
        self._is_settings_expanded = False
        self.bar_label.setVisible(False)
        self.settings_widget.setVisible(False)
        self._divider_widget.setVisible(False)
        self.quota_widget.setVisible(True)
        self._set_quota_mini(False)
        if self._last_good is not None:
            self._show_pace(self._last_good, max(0.0, min(100.0, self._last_good.remaining)))
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
        """小条里的剩余额度跟主窗同步，颜色按使用快慢（节奏色）决定。

        不是按剩余量颜色：小条里只显示百分比，没有节奏条和节奏文案，
        颜色就是小条里唯一的快慢信号。剩余 77% 按剩余量算是绿，
        但快 10% 按节奏算是橙，小条就该是橙，才看得出用得快。
        节奏色跟完整窗体的节奏文案同款（compute_pace 的 color）：
        慢绿、持平黄、快橙、很快红；没有重置时间时回退到剩余量颜色。
        主窗的大字百分比颜色不变，仍按剩余量（<20% 红、<50% 黄、否则绿）。
        """
        if self._last_good is not None:
            remaining = max(0.0, min(100.0, self._last_good.remaining))
            self.bar_label.setText(f"{remaining:.0f}%")
            color = _remaining_color(remaining)
            reset = self._last_good.weekly_reset_at
            if reset is not None:
                try:
                    now = datetime.now().astimezone()
                    reset_local = reset if reset.tzinfo is not None else reset.replace(tzinfo=now.tzinfo)
                    if reset_local.tzinfo is not None:
                        reset_local = reset_local.astimezone(now.tzinfo)
                    color = compute_pace(reset_local, now, remaining).color
                except Exception:
                    pass
            self.bar_label.setStyleSheet(f"color: {color};")
        else:
            self.bar_label.setText("—")
            self.bar_label.setStyleSheet("color: #4ADE80;")

    def _set_quota_mini(self, mini: bool) -> None:
        # mini=True = 设置展开时的上方：只留剩余额度百分比及进度条，
        # 节奏和重置时间都不显示（不是左对齐的迷你版，是上下结构的顶块）。
        # mini=False = 正常完整窗体：百分比、进度条、节奏、重置时间都显示。
        # 百分比字号两边都是 44pt、居中，上下结构不需要缩到左上角。
        font = QFont()
        font.setBold(True)
        font.setPointSize(44)
        self.remaining_label.setFont(font)
        self.remaining_label.setAlignment(Qt.AlignCenter)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        pace_font = QFont()
        pace_font.setBold(True)
        pace_font.setPointSize(10)
        self.pace_label.setFont(pace_font)
        self.pace_label.setAlignment(Qt.AlignCenter)
        if mini:
            self.pace_widget.setVisible(False)
            self.time_label.setVisible(False)
        else:
            self.time_label.setVisible(True)
            # 节奏是否显示由 _show_pace 按数据决定，这里不强制显示，
            # 否则没数据时也会出现一个“—”的空节奏区。

    def _update_login_status(self) -> None:
        logged_in = self._session.has_token
        # 账号信息暂时不显示（2026-10-23 Ren 定）：标签始终隐藏，
        # 不写“当前账号：…”也不写“未登录”。登录状态只靠按钮二选一：
        # 未登录只显登录，已登录只显退出。
        self.login_status_label.setVisible(False)
        self.login_button.setVisible(not logged_in)
        self.logout_button.setVisible(logged_in)

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

    def _on_exit_clicked(self) -> None:
        # 必须调 QApplication.quit()，不能只调 self.close()：
        # 主窗是 Qt.Tool 工具窗，Qt 默认不给工具窗设 WA_QuitOnClose，
        # close() 只关窗口、事件循环不退，进程会无窗口残留，
        # 还占着 dist 里的 DLL，之后打包删 dist 就会 WinError 5。
        QApplication.quit()

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
        # 设置展开时上方只留百分比和进度条，节奏不显示，
        # 即使刚刷新到数据也不把节奏区顶出来。
        if self._is_settings_expanded:
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
        # 换行兜底要配合高度自适应：万一 Windows 字体更宽、
        # 节奏文案换成两行，窗体高度要跟着长一截，否则第二行
        # 还是会被裁；小条、设置展开、形变中不调，免得把小条
        # 撑回完整窗体或把设置面板高度打乱。
        if not self._is_bar and not self._is_settings_expanded and not self._suction_animating and not self._settings_morphing and not self._reveal_morphing:
            self.updateGeometry()
            self.adjustSize()
