@echo off
REM Windows 启动脚本：用 python 跑 main.py。
cd /d %~dp0
python main.py %*
