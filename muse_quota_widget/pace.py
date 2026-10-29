"""用量节奏（第三版）的纯计算，与界面无关，可单测。

平均线：周期按 7 天计，起点 = 重置时间 - 7 天，
平均速度 = 100% / 7 天 ≈ 每天 14.3%；当前速度 = 已用% / 已过天数。
快/慢/持平、颜色、白点位置、预计用完时间全部按当前速度算，
不再按累计百分点差 Δ 算——Δ 在周期初期几乎恒为 0，
会把“几天后就用完”的速度标成持平（2026-10-29 实测：
周期刚过 1 小时、已用 2%，Δ 只有 1.3 个百分点、标持平，
但速度是平均线的近 3 倍、预计 10-31 就用完，前后矛盾）。
快/慢的 % 是速度比平均线快/慢的百分比，不是累计百分点差：
速度在平均线 ±10% 内算持平，快 10%~50% 橙色、快 50% 以上红色，
慢 10% 以上青色。
白点位置：速度偏差（比平均线快/慢的比例）钳制到 [-100%, +100%]
再映射到刻度 0 ~ 1，中央 = 平均速度，偏左慢、偏右快。
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


def pace_color(excess_pct: float) -> str:
    """按速度偏差着色：参数是速度比平均线快/慢的百分比。"""
    if excess_pct <= -10:
        # 慢：青色（跟持平的绿区分得开）。
        return "#22D3EE"
    if excess_pct <= 10:
        # 持平：绿色。
        return "#22C55E"
    if excess_pct <= 50:
        # 快：橙色。
        return "#F97316"
    # 很快：红色。
    return "#EF4444"


def compute_pace(reset_local: datetime, now: datetime, remaining: float) -> PaceInfo:
    cycle_start = reset_local - timedelta(days=7)
    elapsed_days = (now - cycle_start).total_seconds() / 86400
    elapsed_days = max(0.0, min(7.0, elapsed_days))
    expected = elapsed_days / 7 * 100
    used = 100 - remaining
    delta = used - expected

    # 速度偏差：当前速度比平均速度快/慢的百分比。
    # 已过天数为 0 时算不出速度，偏差按 0、标持平。
    avg_speed = 100.0 / 7.0
    if elapsed_days > 0:
        speed = used / elapsed_days
        excess_pct = (speed / avg_speed - 1.0) * 100.0
    else:
        speed = 0.0
        excess_pct = 0.0
    # 白点：速度偏差钳制到 [-100%, +100%] 再映射到 0~1。
    fraction = (max(-100.0, min(100.0, excess_pct)) / 100.0 + 1.0) / 2.0
    if remaining <= 0:
        # 已经用完：不再写快/慢和预计用完，文案只剩“已用完”，
        # 颜色直接用最快的红，跟主窗 0% 的红字一致。
        return PaceInfo(
            expected=expected,
            used=used,
            delta=delta,
            color="#EF4444",
            label="已用完",
            projected=None,
            fraction=fraction,
        )

    if excess_pct <= -10:
        label = f"慢 {abs(excess_pct):.0f}%"
    elif excess_pct >= 10:
        label = f"快 {excess_pct:.0f}%"
    else:
        label = "持平"

    projected: Optional[str] = None
    if elapsed_days > 0:
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
        color=pace_color(excess_pct),
        label=label,
        projected=projected,
        fraction=fraction,
    )
