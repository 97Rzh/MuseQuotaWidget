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

    # Windows 任务栏分组（保留作兼容）：主窗已是 Qt.Tool 工具窗，
    # 本来就不进任务栏、不显示任务栏图标；这里的 ID 只影响
    # 万一有非工具窗（如登录对话框）时的分组，不会再让主窗
    # 在任务栏出现。必须在建窗口之前设。
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
    # 故意不建系统托盘（QSystemTrayIcon）：启动时不出现托盘图标、
    # 右下角也不出现托盘图标，退出只走设置面板里的“退出软件”
    # 按钮（FloatingWindow 里调 self.close()）。全仓任何地方
    # 都不要再加托盘，否则就违背这条定版要求。

    # 运行时应用图标：主窗是 Tool 窗故不进任务栏，图标主要用于
    # 登录对话框等非工具窗和打包产物外观；找不到图标文件时
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
