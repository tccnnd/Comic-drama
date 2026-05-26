@echo off
setlocal

cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo Python virtual environment not found:
  echo %PYTHON%
  echo.
  echo Please create/install the .venv first.
  pause
  exit /b 1
)

echo Starting mock TTS provider...
"%PYTHON%" "%~dp0scripts\check_mock_tts_provider.py"

if errorlevel 1 (
  start "" "%PYTHON%" "%~dp0scripts\mock_tts_provider.py" --port 8010
  echo Mock TTS provider launched on http://127.0.0.1:8010/health
) else (
  echo Mock TTS provider is already running.
)

endlocal
