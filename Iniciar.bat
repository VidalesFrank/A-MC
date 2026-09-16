@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Modelador de muros de contencion - SAP2000
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python en el PATH.
    echo         Instale Python 3.10 o superior desde python.org
    pause
    exit /b 1
)

python -c "import fastapi, uvicorn, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias, esto tarda un momento...
    python -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion de dependencias.
        pause
        exit /b 1
    )
)

echo Iniciando servidor local en http://127.0.0.1:8777
echo Cierre esta ventana para detener la aplicacion.
echo.

start "" http://127.0.0.1:8777
python -m uvicorn app.main:app --host 127.0.0.1 --port 8777 --log-level warning

endlocal
