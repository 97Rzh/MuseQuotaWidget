"""本地诊断日志：默认只记“结构”，不记“值”。

记的东西：时间、阶段、HTTP 状态、返回体的字段名、字段类型、
outcome / type / reason / state 这类状态词、有无令牌（布尔值）。
绝不记：访问令牌、viewer_id、session_binding_id、Cookie、
任何能用来冒充登录的值。
例外：log_quota_numbers 那一行会记额度数值本身
（百分比、词元余额等用户自己的额度，不是凭据），专门用于对数；
日志只写本机，不上传、不进仓库，用户自己决定要不要发出来。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .paths import log_path


def log(message: str) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} {message}\n")
    except Exception:
        # 诊断日志写失败时不影响正常流程。
        pass


def _json_kind(value: Any) -> str:
    if value is None:
        return "Null"
    if isinstance(value, bool):
        return "True/False"
    if isinstance(value, (int, float)):
        return "Number"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list):
        return "Array"
    if isinstance(value, dict):
        return "Object"
    return type(value).__name__


def describe_keys(obj: Any) -> str:
    """返回一个 JSON 对象的“字段名:类型”列表，例如 usage:Object, state:String。"""
    if not isinstance(obj, dict):
        return f"(not object: {_json_kind(obj)})"
    if not obj:
        return "(empty object)"
    return ", ".join(f"{k}:{_json_kind(v)}" for k, v in obj.items())
