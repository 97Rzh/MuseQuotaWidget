"""用量节奏（第二版）的纯计算，与界面无关，可单测。

平均线：周期按 7 天计，起点 = 重置时间 - 7 天，
平均应为 = 已过天数 / 7 × 100%；差值 Δ = 已用% - 平均应为%。
颜色只看 Δ（百分点，不用比值，避免周期初期比值爆炸）：
Δ ≤ -5 绿、-5 ~ +5 黄持平、+5 ~ +20 橙、≥ +20 深红。
白点位置：Δ 钳制到 [-25, +25] 再映射到刻度 0 ~ 1，中央 = Δ0。
预计用完：按当前速度（已用 / 已过天数）外推，不是承诺，
速度一变它就变；已过天数为 0 时算不出速度，只写快/慢。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class PaceInfo:
    expected: float
    used: float
    delta: float
    color: str
    label: str
    projected: Optional[str]
    fraction: float

    @property
    def text(self) -> str:
        if self.projected is None:
            return self.label
        return f"{self.label} · {self.projected}"


def pace_color(delta: float) -> str:
    if delta <= -20:
        return "#22C55E"
    if delta <= -5:
        return "#4ADE80"
    if delta <= 5:
        return "#EAB308"
    if delta <= 20:
        return "#F97316"
    return "#EF4444"


def compute_pace(reset_local: datetime, now: datetime, remaining: float) -> PaceInfo:
    cycle_start = reset_local - timedelta(days=7)
    elapsed_days = (now - cycle_start).total_seconds() / 86400
    elapsed_days = max(0.0, min(7.0, elapsed_days))
    expected = elapsed_days / 7 * 100
    used = 100 - remaining
    delta = used - expected

    if delta <= -5:
        label = f"慢 {abs(delta):.0f}%"
    elif delta >= 5:
        label = f"快 {delta:.0f}%"
    else:
        label = "持平"

    projected: Optional[str] = None
    if elapsed_days > 0:
        speed = used / elapsed_days
        if speed <= 0:
            projected = "预计重置时还剩 100%"
        else:
            days_to_100 = 100 / speed
            if days_to_100 <= 7:
                days_early = 7 - days_to_100
                projected = (
                    "预计正好在重置时用完"
                    if days_early <= 0.05
                    else f"预计提前 {days_early:.1f} 天用完"
                )
            else:
                remaining_at_reset = max(0.0, min(100.0, 100 - speed * 7))
                projected = f"预计重置时还剩 {remaining_at_reset:.0f}%"

    fraction = (max(-25.0, min(25.0, delta)) + 25) / 50
    return PaceInfo(
        expected=expected,
        used=used,
        delta=delta,
        color=pace_color(delta),
        label=label,
        projected=projected,
        fraction=fraction,
    )
