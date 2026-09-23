@echo off
REM Starts Groundwork's Streamlit frontend, pointed at the backend started by
REM run_api.bat (port 8001). Run run_api.bat first, in its own window, and
REM leave it running.

cd /d "%~dp0"

call venv\Scripts\activate.bat

set GROUNDWORK_API_URL=http://localhost:8001

echo Starting Groundwork UI (Streamlit) ...
streamlit run app.py
