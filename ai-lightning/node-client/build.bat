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

REM Leggi versione da version.py
for /f "tokens=2 delims== " %%a in ('findstr /C:"VERSION = " version.py') do set VERSION=%%~a

REM Build exe
echo.
echo Building executable (version %VERSION%)...
pyinstaller --clean build.spec

echo.
echo ========================================
if exist "dist\LightPhon-Node.exe" (
    echo BUILD COMPLETATO!
    echo L'eseguibile si trova in: dist\LightPhon-Node.exe
    
    REM Copia nella cartella releases con nome versione
    if not exist "..\server\static\releases" mkdir "..\server\static\releases"
    copy /Y "dist\LightPhon-Node.exe" "..\server\static\releases\LightPhon-Node-%VERSION%.exe"
    echo.
    echo Copiato in: server\static\releases\LightPhon-Node-%VERSION%.exe
)
echo ========================================
pause
