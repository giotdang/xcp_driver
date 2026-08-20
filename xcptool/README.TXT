================================================================================
xcptool - Setup and Quick Start Guide
================================================================================

Welcome to xcptool!
This is a cross-platform XCP master tool designed for ECU measurement and calibration over CAN/CAN FD. Follow the instructions below to get started quickly.

--------------------------------------------------------------------------------
PREREQUISITES
--------------------------------------------------------------------------------
1. Python 3.11 or higher must be installed on your computer.
2. Download Python here: https://www.python.org/downloads/
   * IMPORTANT NOTE: During Python installation on Windows, make sure to check
     the option "Add Python to PATH" on the first setup screen.

--------------------------------------------------------------------------------
STEP 1: SETUP ENVIRONMENT (Run Once)
--------------------------------------------------------------------------------
1. Navigate to the `xcptool` project folder.
2. Double-click the `setup.bat` file.
3. A terminal window will open and automatically:
   - Check your Python version.
   - Create an isolated virtual environment (`.venv`).
   - Download and install all required dependencies.
4. When the process finishes with `[SUCCESS]`, press any key to close the window.

--------------------------------------------------------------------------------
STEP 2: RUNNING THE APPLICATION
--------------------------------------------------------------------------------

A. Standard Mode (Real Hardware / Default):
   - Double-click `run.bat`.
   - By default, xcptool starts in Real Session mode to connect to physical
     CAN adapters (Vector, PEAK PCAN, CANable / slcan, Kvaser, etc.).

B. Simulation Mode (Virtual Bus / No Hardware Required):
   - If you do not have physical CAN hardware connected, you can run the tool
     with a built-in virtual FakeSlave simulator.
   - Open Command Prompt (cmd) or PowerShell in this folder and run:
     
     	run.bat --session fake

--------------------------------------------------------------------------------
ADDITIONAL TIPS & FEATURES
--------------------------------------------------------------------------------
- CAN Configuration:
  You can configure CAN bitrates, CAN FD data rates, CAN IDs, and padding in the
  "Select CAN Interface" dialog upon opening the app or connecting.
================================================================================
