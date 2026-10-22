"""用量节奏刻度：渐变条 + 中央白线 + 白点，QPainter 手绘。

渐变绿→黄→红，中央白线 = 平均线，白点位置 = fraction（0~1），
中央 = 平均线（fraction 0.5），偏左慢、偏右快。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


class PaceScaleWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self._fraction = 0.5

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        height = self.height()
        bar_y = (height - 14) // 2
        bar_h = 14

        gradient = QLinearGradient(0, 0, width, 0)
        gradient.setColorAt(0.0, QColor("#22C55E"))
        gradient.setColorAt(0.5, QColor("#EAB308"))
        gradient.setColorAt(1.0, QColor("#EF4444"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(0, bar_y, width, bar_h, 7, 7)

        # 中央白线 = 平均线
        cx = width // 2
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawLine(cx, 0, cx, height)

        # 白点 = 实际偏差，中心对准 fraction 位置，两端钳制在条内
        dot_r = 8
        dot_cx = max(dot_r, min(width - dot_r, int(self._fraction * width)))
        dot_cy = height // 2
        painter.setPen(QPen(QColor("#111827"), 2))
        painter.setBrush(QColor("white"))
        painter.drawEllipse(dot_cx - dot_r, dot_cy - dot_r, dot_r * 2, dot_r * 2)
