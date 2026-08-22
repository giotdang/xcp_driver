@echo off
echo ==============================================
echo xcptool Setup Environment
echo ==============================================

:: Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH.
    echo Please install Python 3.11 or newer from https://www.python.org/downloads/
    echo Remember to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [INFO] Python found:
python --version

:: Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo [INFO] Creating virtual environment (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Virtual environment (.venv) already exists.
)

:: Activate virtual environment and install requirements
echo [INFO] Activating virtual environment and installing dependencies...
call .venv\Scripts\activate.bat

:: Upgrade pip
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

:: Install package
echo [INFO] Installing xcptool and its dependencies...
:: Install normal dependencies plus 'slcan' backend optional dependency
pip install -e .[slcan]

if %errorlevel% equ 0 (
    echo ==============================================
    echo [SUCCESS] xcptool installed successfully!
    echo ==============================================
    echo You can now run the tool by double clicking "run.bat".
    echo ==============================================
) else (
    echo [ERROR] Installation failed. Check the errors above.
)
pause
