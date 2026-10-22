#!/usr/bin/env python3
"""MuseQuotaWidget 入口：Mac / Windows 通用。

运行前先装依赖：
    python3 -m pip install -r requirements.txt
然后：
    python3 main.py
Mac 也可以双击 run.sh（或在终端里 ./run.sh）。
"""

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("缺少 PySide6，请先运行：python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("MuseQuotaWidget")
    # QtWebEngine 的导入放在 QApplication 之后：登录窗 / 后台登录
    # 需要它时才在 webengine.py 里懒加载，主窗本身不需要它。
    from muse_quota_widget.main_window import FloatingWindow

    window = FloatingWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
