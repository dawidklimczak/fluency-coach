@echo off
setlocal
rem Uruchamia Speaking Automaticity Trainer: backend (FastAPI :8000)
rem i frontend (Vite :5173) w osobnych oknach, potem otwiera przegladarke.
cd /d "%~dp0"

if not exist "apps\api\.venv\Scripts\python.exe" (
  echo [!] Brak virtualenva: apps\api\.venv
  echo     Utworz go tak:
  echo       python -m venv apps\api\.venv
  echo       apps\api\.venv\Scripts\pip install -r apps\api\requirements.txt
  echo       apps\api\.venv\Scripts\python -m spacy download en_core_web_sm
  pause
  exit /b 1
)

if not exist "apps\web\node_modules" (
  echo [i] Pierwsze uruchomienie - instaluje zaleznosci frontendu...
  pushd apps\web
  call npm install
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
)

echo [i] Startuje backend na http://127.0.0.1:8000 ...
start "EnglishHelper API" cmd /k "cd /d %~dp0apps\api && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [i] Startuje frontend na http://localhost:5173 ...
start "EnglishHelper Web" cmd /k "cd /d %~dp0apps\web && npm run dev"

rem odczekaj ~4 s na start serwerow (ping zamiast timeout - dziala tez bez konsoli)
ping -n 5 127.0.0.1 >nul
start http://localhost:5173
echo [i] Gotowe. Zamkniecie okien "EnglishHelper API" i "EnglishHelper Web" zatrzymuje aplikacje.
