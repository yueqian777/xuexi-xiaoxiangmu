@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\SoftwareDownload\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo Starting INTP Study Manager...
echo Project: %CD%
echo Python: %PYTHON_EXE%
echo.

"%PYTHON_EXE%" -m streamlit run app.py

if errorlevel 1 (
    echo.
    echo Startup failed. Please check the error above.
    pause
)
