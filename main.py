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

    # Windows 任务栏分组：不设这个 ID，窗口会跟 python.exe
    # 归到一组、任务栏显示 Python 图标；设专属 ID 后才按
    # 本应用分组、显示本应用的图标。必须在建窗口之前设。
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Levana.MuseQuotaWidget"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("MuseQuotaWidget")

    # 运行时应用图标：任务栏 / Dock / Alt-Tab 显示做的那个图标，
    # 而不是默认的 Python / PyInstaller 图标。找不到图标文件时
    # 按默认处理，不因此启动失败。
    app_icon = None
    try:
        from muse_quota_widget.app_icon import load_app_icon

        app_icon = load_app_icon()
        if app_icon is not None:
            app.setWindowIcon(app_icon)
    except Exception:
        app_icon = None

    # QtWebEngine 的导入放在 QApplication 之后：登录窗 / 后台登录
    # 需要它时才在 webengine.py 里懒加载，主窗本身不需要它。
    from muse_quota_widget.main_window import FloatingWindow

    window = FloatingWindow()
    if app_icon is not None:
        window.setWindowIcon(app_icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
