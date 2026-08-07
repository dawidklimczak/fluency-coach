@echo off
setlocal
rem Uruchamia Speaking Automaticity Trainer lokalnie: jeden proces, jeden port.
rem Frontend jest budowany raz i serwowany przez backend z http://127.0.0.1:8000
cd /d "%~dp0"

if not exist "apps\api\.venv\Scripts\python.exe" (
  echo [!] Brak srodowiska Pythona: apps\api\.venv
  echo.
  echo     Uruchom najpierw setup.bat - przygotuje wszystko automatycznie.
  echo.
  pause
  exit /b 1
)

if not exist "apps\web\dist\index.html" (
  echo [i] Frontend nie jest jeszcze zbudowany - buduje go teraz...
  if not exist "apps\web\node_modules" (
    pushd apps\web
    call npm install || (popd & pause & exit /b 1)
    popd
  )
  pushd apps\web
  call npm run build || (popd & pause & exit /b 1)
  popd
)

echo.
echo [i] Aplikacja startuje pod adresem http://127.0.0.1:8000
echo [i] To okno musi pozostac otwarte. Zamkniecie go zatrzymuje aplikacje.
echo.

rem otworz przegladarke po chwili, rownolegle do startu serwera
start "" cmd /c "ping -n 5 127.0.0.1 >nul & start http://127.0.0.1:8000"

cd apps\api
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
