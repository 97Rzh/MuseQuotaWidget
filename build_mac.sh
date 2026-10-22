#!/bin/zsh
# 在 Mac 上把 MuseQuotaWidget 打包成 .app（双击就能打开，不用走终端）。
# 用法：在仓库根目录跑 ./build_mac.sh
# 产物：dist/MuseQuotaWidget.app（可直接拖到“应用程序”里）
#
# 注意：
# - 必须在 Mac 上跑：在 Linux 上打出来的是 Linux 程序，不是 Mac 的 .app。
# - 用 --windowed（不是 --onefile）：QtWebEngine 的子进程要跟 .app
#   放在一起，--onefile 解压到临时目录容易让登录窗找不到 WebEngine。
# - 打出来的 .app 没有签名，第一次打开会被 Gatekeeper 拦：
#   右键点 .app → “打开” → 再点“打开”，或者跑
#   xattr -cr dist/MuseQuotaWidget.app 后再双击。
# - 设置、日志、浏览器 Cookie 还是存在
#   ~/Library/Application Support/MuseQuotaWidget/，跟终端版同一套，
#   所以 .app 版不用重新登录，第一次打开就能直接显示额度
#   （前提是终端版已经登录过、Cookie 还没过期）。

set -e
cd "$(dirname "$0")"

python3 -m pip install -r requirements.txt pyinstaller

# iconutil 是 macOS 自带的：把 iconset 转成 PyInstaller 要的 .icns。
iconutil -c icns assets/icon.iconset -o assets/icon.icns

python3 -m PyInstaller \
  --clean --noconfirm \
  --windowed \
  --name MuseQuotaWidget \
  --icon assets/icon.icns \
  --osx-bundle-identifier com.levana.musequotawidget \
  main.py

echo "Built: dist/MuseQuotaWidget.app"
ls -d dist/MuseQuotaWidget.app
