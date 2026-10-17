@echo off
REM JARVIS Legal OS launcher for Windows. Double click, or right click and
REM "Send to > Desktop (create shortcut)", then set the icon to assets\jarvis_icon.ico
cd /d "%~dp0\.."

if not exist ".venv" (
  echo First run: setting up JARVIS, one time...
  python -m venv .venv
  .venv\Scripts\pip install -q -r requirements.txt
)

start "" /min .venv\Scripts\streamlit run app.py --server.port 8501
timeout /t 5 /nobreak >nul

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist %CHROME% (
  start "" %CHROME% --app=http://localhost:8501 --start-fullscreen
) else (
  start "" http://localhost:8501
)
