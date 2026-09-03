@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

echo.
echo Starting IFP Repair Evaluation web server at http://localhost:6969
echo Press Ctrl+C to stop.
echo.
start "" http://localhost:6969
python -m uvicorn app.main:app --host 0.0.0.0 --port 6969
