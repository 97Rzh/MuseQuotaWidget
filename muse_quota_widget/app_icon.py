"""运行时应用图标：让任务栏 / Dock / Alt-Tab 显示做的那个图标，
而不是默认的 Python / PyInstaller 图标。

为什么只改打包时的 --icon 不够：
- 打包的 --icon 只改 exe / .app 文件本身在资源管理器里看起来的样子，
  运行时窗口在任务栏里的图标是 Qt 的窗口图标，没设就是默认图标。
- 从源码跑（python main.py）时更明显：进程是 python.exe，
  Windows 任务栏默认会按进程分组显示 Python 图标。

所以这里在运行时也设一次图标，来源是 assets/icon.png：
- 源码跑：仓库根目录下的 assets/icon.png（包的上一级）；
- 打包后跑：PyInstaller 把 --add-data 带进来的
  sys._MEIPASS/assets/icon.png（打包脚本里已加这条，
  没加的话打包版就找不到图标，只能退回默认图标）。

Windows 上另外设 AppUserModelID：不设的话，Windows 会把
这个窗口跟 python.exe 归到一组，任务栏仍可能显示 Python 图标；
设一个专属 ID 后，任务栏按这个 ID 分组、显示本应用的图标。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def find_icon_path() -> Optional[Path]:
    candidates = []
    # 打包后：PyInstaller 解压目录。
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "icon.png")
    # 源码：muse_quota_widget/ 的上一级就是仓库根。
    candidates.append(Path(__file__).resolve().parent.parent / "assets" / "icon.png")
    # 兜底：当前工作目录下的 assets/（从仓库根跑时就是这里）。
    candidates.append(Path.cwd() / "assets" / "icon.png")
    for path in candidates:
        try:
            if path.is_file():
                return path
        except Exception:
            continue
    return None


def load_app_icon():
    """返回 QIcon，找不到图标文件时返回 None（调用方按默认处理）。"""
    path = find_icon_path()
    if path is None:
        return None
    try:
        from PySide6.QtGui import QIcon

        icon = QIcon(str(path))
        return icon if not icon.isNull() else None
    except Exception:
        return None
