@echo off
rem Usage: run.bat [-c PATH] [-s fake] [--light] [--log-level LEVEL] [--selftest]
rem   -c PATH  / --config PATH   load and save state to PATH (default: .\config.toml if present)
rem   -s VALUE / --session VALUE 'fake' runs with no hardware/backend (default: real)
rem   no args                    unchanged: loads .\config.toml if present
rem   -h / --help                full option list
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