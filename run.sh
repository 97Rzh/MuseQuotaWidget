#!/bin/bash
# Mac / Linux 启动脚本：cd 到脚本所在目录后用 python3 跑 main.py。
cd "$(dirname "$0")"
exec python3 main.py "$@"
