@echo off
title Daily Mix
cd /d "%~dp0"

set "PYEXE="
if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" set "PYEXE=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not defined PYEXE (
  where python >nul 2>nul
  if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
  where py >nul 2>nul
  if not errorlevel 1 set "PYEXE=py"
)
if not defined PYEXE (
  echo.
  echo   Python 3.10+ was not found.
  echo   Install it from https://www.python.org/downloads/ and try again.
  echo.
  pause
  exit /b 1
)

"%PYEXE%" app.py
if errorlevel 1 pause
