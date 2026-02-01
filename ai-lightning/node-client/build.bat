@echo off
echo ========================================
echo AI Lightning Node - Build Script
echo ========================================
echo.

REM Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato!
    echo Installa Python da https://www.python.org/
    pause
    exit /b 1
)

REM Crea virtual environment
if not exist "venv" (
    echo Creazione virtual environment...
    python -m venv venv
)

REM Attiva venv
call venv\Scripts\activate.bat

REM Installa dipendenze
echo.
echo Installazione dipendenze...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

REM Build exe
echo.
echo Building executable...
pyinstaller --clean build.spec

echo.
echo ========================================
if exist "dist\AI-Lightning-Node.exe" (
    echo BUILD COMPLETATO!
    echo L'eseguibile si trova in: dist\AI-Lightning-Node.exe
) else (
    echo ERRORE durante il build!
)
echo ========================================
pause
