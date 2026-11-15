@echo off
setlocal
if /i "%~1"=="--help" (
  echo Run the already authorized, never-started Guard check with fixed request 1954.
  echo The supervisor stays ordinary. Windows asks separately for administrator consent.
  echo Only the fixed new Guard is started once, checked, and stopped.
  echo No existing service, user database, network policy, or model is changed.
  exit /b 0
)
pushd "%~dp0.."
if errorlevel 1 exit /b 2
echo Guard check: Windows administrator confirmation will be requested.
echo Keep this window open until the check finishes.
".venv\Scripts\python.exe" -B "tools\python-v20.py" "backend\tests\infrastructure\v20_guard_system_bootstrap_worker.py" ^
 --start-stop --allow-system-changes ^
 --installer "%CD%\backend\distributions\windows\guard-installer-prepared-20261114-2059" ^
 --installer-sha256 1fafdfb8a68e2b500b448f3ec95043f6f9c0a0df89f999c3011d4ffd9fd4849b ^
 --request "%CD%\backend\distributions\windows\guard-installation-prepared-20261114-1954\guard-installation.v1.json" ^
 --request-sha256 4ee0f56c2aca50478ab8bbca34bff940ce9709edc8f7f7f8fd20930076db6ce4 ^
 --original-installer-package "%CD%\backend\distributions\windows\guard-installer-prepared-20261114-1952"
set "taskGuardExit=%ERRORLEVEL%"
popd
echo.
echo Guard check finished with code %taskGuardExit%.
echo Do not rerun after an unknown outcome.
pause
exit /b %taskGuardExit%
