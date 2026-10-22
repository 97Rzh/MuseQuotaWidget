"""平台相关的本地路径：只存设置与诊断日志，不存账号与令牌。

Windows：%LOCALAPPDATA%\\MuseQuotaWidget
macOS：~/Library/Application Support/MuseQuotaWidget
Linux：~/.local/share/MuseQuotaWidget（或 $XDG_DATA_HOME）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "MuseQuotaWidget"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MuseQuotaWidget"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "MuseQuotaWidget"
    return Path.home() / ".local" / "share" / "MuseQuotaWidget"


def settings_path() -> Path:
    return app_dir() / "settings.json"


def log_path() -> Path:
    return app_dir() / "muse-debug.log"


def webengine_dir() -> Path:
    """QtWebEngine 持久化数据目录（Cookie 就存在这里，相当于 C# 版的 WebView2 文件夹）。"""
    return app_dir() / "QtWebEngine"
