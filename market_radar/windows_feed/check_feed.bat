@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==== 최근 Kiwoom Feed 로그 ====
if exist kiwoom_feed.log (
  powershell -NoProfile -Command "Get-Content -Path 'kiwoom_feed.log' -Tail 30"
) else (
  echo 아직 로그가 없습니다.
)
pause
