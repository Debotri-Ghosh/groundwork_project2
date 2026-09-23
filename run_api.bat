@echo off
REM Starts Groundwork's backend: Qdrant + Postgres, then the FastAPI server.
REM Uses port 8001 because port 8000 is often occupied by the FleetMind project
REM on this machine. If that's no longer the case, change 8001 below (and the
REM matching value in run_ui.bat) back to 8000.

cd /d "%~dp0"

echo Starting Qdrant + Postgres (docker compose)...
docker compose up -d

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Starting Groundwork API on http://localhost:8001 ...
python -m uvicorn main:app --reload --port 8001
