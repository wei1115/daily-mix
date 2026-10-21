@echo off
title Stop Daily Mix
setlocal enabledelayedexpansion
set "FOUND="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c:":8787" ^| findstr /i "LISTENING"') do (
  echo Stopping PID %%a ...
  taskkill /PID %%a /F >nul 2>nul
  set "FOUND=1"
)
if not defined FOUND (
  echo Daily Mix is not running on port 8787.
) else (
  echo Stopped.
)
pause
