@echo off
rem Sets up and starts Artemis on this computer (Windows). Run it again any time to start Artemis.
cd /d "%~dp0"

python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>nul
if errorlevel 1 (
  echo Artemis needs Python 3.12 or later. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during installation, then run this file again.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating the Python environment...
  python -m venv .venv || goto fail
)
call .venv\Scripts\activate.bat || goto fail

echo Installing packages. The first run downloads about 200 MB; later runs are quick.
python -m pip install --disable-pip-version-check -q -r requirements.txt || goto fail
python -m playwright install chromium || goto fail

echo.
echo Artemis is starting. Open http://localhost:8000 in your browser.
echo Account emails are printed in this window. Press Ctrl+C to stop.
echo.
python -m uvicorn main:app --port 8000
goto :eof

:fail
echo.
echo Setup failed. Read the messages above, or check your internet connection and try again.
pause
exit /b 1
