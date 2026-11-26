@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run Setup_SWOTFlow_Lite.ps1 in PowerShell to install the application environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m swotflow_lite
if errorlevel 1 pause
