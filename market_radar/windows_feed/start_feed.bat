@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo 먼저 setup_windows.bat 을 실행하세요.
  pause
  exit /b 1
)
.venv\Scripts\python.exe kiwoom_windows_feed.py
pause
