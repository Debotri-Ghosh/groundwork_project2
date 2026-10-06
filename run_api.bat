@echo off
REM Starts Groundwork's backend: Qdrant + Postgres, then the FastAPI server.
REM Uses port 8002: 8000 is often occupied by the FleetMind project on this
REM machine, and 8001 got stuck held by an unkillable stale process during
REM development. If neither conflict applies for you, 8000 is fine too --
REM just change this and the matching value in run_ui.bat.

cd /d "%~dp0"

echo Starting Qdrant + Postgres (docker compose)...
docker compose up -d

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Starting Groundwork API on http://localhost:8002 ...
python -m uvicorn main:app --reload --port 8002
