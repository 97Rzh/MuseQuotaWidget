"""Muse 额度直连：实现思路参照 HuiAnnn/ai-quota 的 Muse 部分，
C# 版（MuseApi.cs）已原样移植到 Python，关键约定不变：

- 登录在应用自己的浏览器数据文件夹里完成，不用系统浏览器、
  不用 Muse 原生应用的登录状态；
- 令牌只存在内存里，绝不写盘、绝不进日志；
- 令牌只发给 hatch-api.meta.ai 这一个主机，不带 Cookie；
- 额度快照里只有百分比、时间和词元余额，不含任何凭据。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from . import diagnostics


class MuseAuthKind:
    LOGIN_REQUIRED = "LoginRequired"
    ACCESS_RESTRICTED = "AccessRestricted"
    CHECKPOINT_REQUIRED = "CheckpointRequired"
    TOKEN_UNAVAILABLE = "TokenUnavailable"
    INVALID_RESPONSE = "InvalidResponse"
    NETWORK_UNAVAILABLE = "NetworkUnavailable"
    QUOTA_ACCESS_REJECTED = "QuotaAccessRejected"
    RATE_LIMITED = "RateLimited"
    ACCOUNT_CHANGED = "AccountChanged"
    REQUEST_REJECTED = "RequestRejected"


_MESSAGES_ZH = {
    MuseAuthKind.LOGIN_REQUIRED: "尚未完成 Muse 网页登录（或会话已失效）。请在登录窗口登录后重试。",
    MuseAuthKind.ACCESS_RESTRICTED: "Muse 账号尚未获得访问权限。请在登录窗口完成访问流程。",
    MuseAuthKind.CHECKPOINT_REQUIRED: "Muse 需要验证账号。请在登录窗口完成验证后重试。",
    MuseAuthKind.TOKEN_UNAVAILABLE: "网页登录已通过，但 Muse 未提供额度访问令牌；此会话的额度读取尚未完成。",
    MuseAuthKind.INVALID_RESPONSE: "Muse 返回了当前版本无法识别的数据。",
    MuseAuthKind.NETWORK_UNAVAILABLE: "网络请求失败或超时。请稍后重试。",
    MuseAuthKind.QUOTA_ACCESS_REJECTED: "Muse 额度接口拒绝了当前网页凭据；尚未确认网页令牌可访问额度。",
    MuseAuthKind.RATE_LIMITED: "Muse 暂时限制了请求频率。请稍后重试。",
    MuseAuthKind.ACCOUNT_CHANGED: "账号或会话已切换，请重试。",
}


class MuseAuthException(Exception):
    def __init__(self, kind: str, status_code: Optional[int] = None):
        super().__init__(kind)
        self.kind = kind
        self.status_code = status_code

    @property
    def message_zh(self) -> str:
        if self.kind == MuseAuthKind.REQUEST_REJECTED:
            if self.status_code is not None:
                return f"Muse 返回 HTTP {self.status_code}，请稍后重试。"
            return "Muse 返回了无法识别的错误，请稍后重试。"
        return _MESSAGES_ZH.get(self.kind, "未知错误。")


@dataclass
class MuseCredential:
    """仅存内存的凭据。Token 与指纹成对出现，指纹变了就视为换号。"""

    token: str
    fingerprint: str

    @staticmethod
    def fingerprint_for(viewer_id: str, binding_id: Optional[str]) -> str:
        # 与 ai-quota 一致：SHA256(viewer_id + '\0' + session_binding_id) 的十六进制小写。
        raw = (viewer_id + "\0" + (binding_id or "")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass
class QuotaData:
    """悬浮窗展示的一份额度快照。字段故意只保留“展示用”的数，不含任何账号凭证。"""

    plan: str = "免费版（无订阅）"
    used_percent: float = 0.0
    remaining_percent: Optional[float] = None
    weekly_reset_at: Optional[datetime] = None
    additional_tokens_left: str = ""
    additional_tokens_used_percent: float = 0.0
    updated_at: Optional[datetime] = None

    @property
    def remaining(self) -> float:
        if self.remaining_percent is not None:
            return self.remaining_percent
        return 100 - self.used_percent


def _try_get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict) and name in obj:
        return obj[name]
    return None


def _try_get_string(obj: Any, *names: str) -> Optional[str]:
    for name in names:
        value = _try_get(obj, name)
        if isinstance(value, str):
            return value
    return None


def _try_get_number(obj: Any, *names: str) -> Optional[float]:
    for name in names:
        value = _try_get(obj, name)
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            return float(value)
        if isinstance(value, str):
            try:
                parsed = float(value)
            except ValueError:
                continue
            if math.isfinite(parsed) and parsed >= 0:
                return parsed
    return None


def _format_tokens(balance: float) -> str:
    # 只做数值格式化，不做单位换算猜测：1.24e9 就是“12.4亿词元”，
    # 不把它硬说成 31B（那个 31B 是 subscription-status 的另一种口径）。
    if balance >= 100_000_000:
        text = f"{balance / 100_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{text}亿词元"
    return f"{balance:.0f}词元"


def _parse_reset(usage: dict) -> Optional[datetime]:
    # 字符串：ai-quota 只认带日期或带时区偏移的 ISO 格式，照搬，
    # 但一律转本地时间显示——之前直接按原偏移格式化，Unix/ISO 的
    # UTC 时间就原样显示成了 UTC，比本地晚 8 小时。
    raw = _try_get_string(usage, "resets_at", "resetsAt")
    if raw is not None and raw.strip():
        # 只有日期、没有时刻时，只精确到天，显示为本地当天零点，
        # 不按 UTC 零点再转本地（那样会变成当天 08:00）。
        if len(raw.strip()) == 10:
            try:
                day = datetime.strptime(raw.strip(), "%Y-%m-%d")
                local_offset = datetime.now().astimezone().utcoffset()
                return day.replace(tzinfo=timezone(local_offset)) if local_offset is not None else day
            except ValueError:
                pass
        try:
            text = raw.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone()
        except ValueError:
            return None

    # 数字：与 ai-quota 不同，这里做了转换，因为已用实测验证过——
    # 网页端 RSC 里的 resetsAt=1793244675（秒）换算后正好是
    # 2026-10-29 11:31 CST，与 subscription-status 的重置时间完全对上，
    # 所以秒级 Unix 时间戳的单位是确定的，不是猜测。
    num = _try_get_number(usage, "resets_at", "resetsAt")
    if num is not None:
        try:
            if num >= 100_000_000_000:
                return datetime.fromtimestamp(num / 1000, tz=timezone.utc).astimezone()
            return datetime.fromtimestamp(num, tz=timezone.utc).astimezone()
        except (ValueError, OverflowError, OSError):
            return None
    return None


def parse_quota(body: str) -> QuotaData:
    """解析 hatch-api 的订阅响应，同时兼容蛇形字段与驼峰字段、嵌套包装。"""
    try:
        root = json.loads(body)
    except json.JSONDecodeError:
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    if not isinstance(root, dict):
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    # usage 优先在顶层找；若 hatch-api 实际把它包了一层
    # （subscription / data / result），也接受，不直接判无法识别。
    usage = _try_get(root, "usage")
    container = root
    if not isinstance(usage, dict):
        for wrapper in ("subscription", "data", "result"):
            inner = _try_get(root, wrapper)
            if isinstance(inner, dict) and isinstance(_try_get(inner, "usage"), dict):
                usage = inner["usage"]
                container = inner
                break
    if not isinstance(usage, dict):
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    percent_used = _try_get_number(usage, "percent_used", "percentUsed")
    if percent_used is None:
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    data = QuotaData(
        plan="Muse",
        used_percent=percent_used,
        remaining_percent=max(0.0, min(100.0, 100 - percent_used)),
        weekly_reset_at=_parse_reset(usage),
        updated_at=datetime.now().astimezone(),
    )

    # topup 字段也可能跟 usage 一起被包在内层对象里。
    topup_balance = _try_get_number(root, "topup_balance", "topupBalance")
    if topup_balance is None:
        topup_balance = _try_get_number(container, "topup_balance", "topupBalance")
    topup_total = _try_get_number(root, "topup_total", "topupTotal")
    if topup_total is None:
        topup_total = _try_get_number(container, "topup_total", "topupTotal")
    if topup_balance is not None:
        data.additional_tokens_left = _format_tokens(topup_balance)
        if topup_total is not None and topup_total > 0:
            data.additional_tokens_used_percent = max(0.0, min(100.0, 100 * (1 - topup_balance / topup_total)))

    label = _try_get_string(root, "usage_row_label", "usageRowLabel")
    if label is None:
        label = _try_get_string(container, "usage_row_label", "usageRowLabel")
    if label and label.strip():
        # usage_row_label 在中文界面下就是“免费版”一类的展示名，优先用它。
        data.plan = label

    return data


def log_quota_shape(body: str) -> None:
    """只记结构不记值：顶层字段名、usage 字段名、state，帮助定位是哪个字段对不上。"""
    try:
        root = json.loads(body)
    except json.JSONDecodeError:
        diagnostics.log("quota invalid: body is not valid JSON")
        return
    line = f"quota invalid: top=[{diagnostics.describe_keys(root)}]"
    if isinstance(root, dict) and isinstance(root.get("usage"), dict):
        line += f" usage=[{diagnostics.describe_keys(root['usage'])}]"
        state = root["usage"].get("state")
        if isinstance(state, str):
            line += f" state={state}"
    diagnostics.log(line)


def log_quota_numbers(body: str) -> None:
    """额外 token 对数专用：把返回体里的数值字段原样记到诊断日志里
    （不记令牌、账号 id、Cookie），用于确认到底哪个字段才是 agent 侧说的 31B。
    这里不做任何换算、不乘系数，看到什么就是什么，绝不为了凑 31 亿去硬改一个数。"""
    try:
        root = json.loads(body)
    except json.JSONDecodeError:
        return
    if not isinstance(root, dict):
        return

    parts: list[str] = []

    def collect(obj: dict, prefix: str) -> None:
        for name, value in obj.items():
            lowered = name.lower()
            # 凭据类字段一律跳过，哪怕它恰好是数字（C# 原逻辑的运算符优先级：id 需同时满足 != tier_id）。
            if (
                "token" in lowered
                or "viewer" in lowered
                or "session" in lowered
                or "auth" in lowered
                or ("id" in lowered and name != "tier_id")
            ):
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                parts.append(f"{prefix}{name}={value}")
            elif isinstance(value, dict) and (prefix == "" or prefix == "usage."):
                # 只深入一层 usage，避免把整棵树都展开。
                collect(value, prefix + name + ".")

    collect(root, "")
    if parts:
        diagnostics.log("quota numbers: " + ", ".join(parts))
