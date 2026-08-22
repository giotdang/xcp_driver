@echo off
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment .venv not found!
    echo Please execute "setup.bat" prior to running this script.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
.venv\Scripts\python.exe -m xcptool.ui.app %*
if %errorlevel% neq 0 (
    pause
)