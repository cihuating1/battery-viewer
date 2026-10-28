@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHON=pythonw
if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe" set PYTHON="%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"

start "" %PYTHON% chargedock_app.py
exit
