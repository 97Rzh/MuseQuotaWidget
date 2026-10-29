"""用量节奏（第二版）的纯计算，与界面无关，可单测。

平均线：周期按 7 天计，起点 = 重置时间 - 7 天，
平均应为 = 已过天数 / 7 × 100%；差值 Δ = 已用% - 平均应为%。
颜色只看 Δ（百分点，不用比值，避免周期初期比值爆炸）：
Δ ≤ -5 青色（慢）、-5 ~ +5 绿色（持平）、+5 ~ +20 橙色（快）、
≥ +20 红色（很快）。
白点位置：Δ 钳制到 [-25, +25] 再映射到刻度 0 ~ 1，中央 = Δ0。
预计用完：按当前速度（已用 / 已过天数）外推，不是承诺，
速度一变它就变；已过天数为 0 时算不出速度，只写快/慢。
节奏颜色：慢青色、持平绿色、快橙色、很快红色。
预计日期时间有限制：只在预计用完时间落在重置时间之前
（含正好等于重置时间）时才写“预计 MM-dd HH:mm 用完”；
预计用完时间在重置时间之后时不写那个日期（重置会先到），
改写“预计重置时还剩 X%”。所以预计日期永远不会超出重置时间。
已经用完（剩余 ≤ 0）时不再写快/慢和预计用完，只写“已用完”。
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
    if delta <= -5:
        # 慢：青色（Ren 在“深绿或者青色”里二选一，取青色，
        # 跟持平的绿区分得开）。
        return "#22D3EE"
    if delta <= 5:
        # 持平：绿色。
        return "#22C55E"
    if delta <= 20:
        # 快：跟以前一样，橙色。
        return "#F97316"
    # 很快：跟以前一样，红色。
    return "#EF4444"


def compute_pace(reset_local: datetime, now: datetime, remaining: float) -> PaceInfo:
    cycle_start = reset_local - timedelta(days=7)
    elapsed_days = (now - cycle_start).total_seconds() / 86400
    elapsed_days = max(0.0, min(7.0, elapsed_days))
    expected = elapsed_days / 7 * 100
    used = 100 - remaining
    delta = used - expected

    fraction = (max(-25.0, min(25.0, delta)) + 25) / 50
    if remaining <= 0:
        # 已经用完：不再写快/慢和预计用完，文案只剩“已用完”，
        # 颜色直接用最快的红，跟主窗 0% 的红字一致；刻度白点
        # 仍按 Δ 位置放，不动它。
        return PaceInfo(
            expected=expected,
            used=used,
            delta=delta,
            color="#EF4444",
            label="已用完",
            projected=None,
            fraction=fraction,
        )

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
                # 快时不再写“提前 X 天”，直接写预计用完的日期时间，
                # 格式跟重置时间一致：MM-dd HH:mm，不带秒。
                # days_to_100 <= 7 保证这个时间不超出重置时间；
                # 正好等于 7 时就是重置时间本身，不用再写“正好”。
                projected_finish = cycle_start + timedelta(days=days_to_100)
                if projected_finish > reset_local:
                    projected_finish = reset_local
                projected = f"预计 {projected_finish:%m-%d %H:%M} 用完"
            else:
                # 慢时预计用完在重置之后，重置会先到，所以不写那个日期，
                # 只写重置时还剩多少，这就是对预计日期时间的限制。
                remaining_at_reset = max(0.0, min(100.0, 100 - speed * 7))
                projected = f"预计重置时还剩 {remaining_at_reset:.0f}%"

    return PaceInfo(
        expected=expected,
        used=used,
        delta=delta,
        color=pace_color(delta),
        label=label,
        projected=projected,
        fraction=fraction,
    )
