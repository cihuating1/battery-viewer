@echo off
chcp 65001 >nul
title 外设电量监控
cd /d "%~dp0"
set PYTHON=python
if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" set PYTHON="%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"

echo 正在启动外设电量监控界面...
start "" %PYTHON% my_devices.py
exit
