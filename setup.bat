@echo off
setlocal
rem Jednorazowe przygotowanie aplikacji: srodowisko Pythona, zaleznosci,
rem modele jezykowe i budowa frontendu. Potem uruchamiasz przez start.bat
cd /d "%~dp0"

echo ============================================
echo   Speaking Automaticity Trainer - instalacja
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [!] Nie znaleziono Pythona.
  echo     Zainstaluj Python 3.11 lub nowszy z https://www.python.org/downloads/
  echo     WAZNE: zaznacz "Add Python to PATH" podczas instalacji.
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [!] Nie znaleziono Node.js.
  echo     Zainstaluj wersje LTS z https://nodejs.org/
  pause
  exit /b 1
)

echo [1/5] Tworze srodowisko Pythona...
if not exist "apps\api\.venv\Scripts\python.exe" (
  python -m venv apps\api\.venv || (pause & exit /b 1)
)

echo [2/5] Instaluje biblioteki (to potrwa kilka minut)...
apps\api\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
apps\api\.venv\Scripts\python.exe -m pip install -r apps\api\requirements.txt || (pause & exit /b 1)

echo [3/5] Pobieram model jezykowy...
apps\api\.venv\Scripts\python.exe -m spacy download en_core_web_sm || (pause & exit /b 1)

echo [4/5] Pobieram model wykrywania mowy...
apps\api\.venv\Scripts\python.exe scripts\download_models.py || (pause & exit /b 1)

echo [5/5] Buduje interfejs...
pushd apps\web
call npm install || (popd & pause & exit /b 1)
call npm run build || (popd & pause & exit /b 1)
popd

echo.
echo ============================================
echo   Gotowe. Uruchamiaj aplikacje przez start.bat
echo ============================================
echo.
pause
