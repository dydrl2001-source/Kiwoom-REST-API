@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3가 필요합니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요.
  pause
  exit /b 1
)
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install requests
python configure_feed.py
echo.
echo 설정이 완료되었습니다.
pause
