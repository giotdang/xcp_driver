@echo off
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Chua tim thay moi truong ao .venv!
    echo Vui long chay file "setup.bat" truoc khi khoi dong ung dung.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m xcptool.ui.app %*
if %errorlevel% neq 0 (
    pause
)