"""本地设置：只存刷新频率（分钟），不存任何账号与令牌。
删了设置文件就恢复默认 5 分钟。"""

from __future__ import annotations

import json

from .paths import settings_path

DEFAULT_INTERVAL_MINUTES = 5


def load_interval_minutes() -> int:
    try:
        path = settings_path()
        if not path.exists():
            return DEFAULT_INTERVAL_MINUTES
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            minutes = data.get("refreshIntervalMinutes")
            if isinstance(minutes, int) and not isinstance(minutes, bool):
                return max(1, min(60, minutes))
    except Exception:
        # 设置文件坏了就用默认值，不崩。
        pass
    return DEFAULT_INTERVAL_MINUTES


def save_interval_minutes(minutes: int) -> None:
    try:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"refreshIntervalMinutes": max(1, min(60, minutes))}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        # 设置保存失败不影响当前这次刷新。
        pass
