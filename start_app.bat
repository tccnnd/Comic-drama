@echo off
setlocal

cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "URL=http://127.0.0.1:8000/"

if not exist "%PYTHON%" (
  echo Python virtual environment not found:
  echo %PYTHON%
  echo.
  echo Please create/install the .venv first.
  pause
  exit /b 1
)

echo Checking Comic Drama server...
call "%~dp0start_mock_tts_provider.bat"
"%PYTHON%" "scripts\check_health.py"

if errorlevel 1 (
  echo Starting backend server in this window...
  echo If the browser opens before the server is ready, refresh it after a few seconds.
  echo.
  start "" "%URL%"
  "%PYTHON%" "scripts\dev_server.py"
  echo.
  echo Backend server stopped.
  pause
  exit /b 0
) else (
  echo Backend server is already running.
)

echo Opening %URL%
start "" "%URL%"
echo.
echo Comic Drama app is running at %URL%
echo This window can be closed.
"%PYTHON%" -c "import time; time.sleep(3)"

endlocal
