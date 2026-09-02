@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo Building RepairEvaluationApp.exe...
pyinstaller --noconfirm --clean --windowed --onefile ^
    --name RepairEvaluationApp ^
    --add-data "assets;assets" ^
    main.py

echo.
echo Build complete.
echo EXE: %CD%\dist\RepairEvaluationApp.exe
pause
