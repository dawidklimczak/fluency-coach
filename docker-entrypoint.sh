#!/bin/sh
set -e

# W kontenerze ruch z hosta przechodzi przez bramę Dockera, więc aplikacja
# nigdy nie widzi klienta jako 127.0.0.1 - reguła fail closed odrzuciłaby
# wszystko. Dlatego hasło jest tu wymagane, także przy pracy lokalnej.
if [ -z "$APP_PASSWORD" ]; then
  echo "[!] APP_PASSWORD nie jest ustawione."
  echo ""
  echo "    W kontenerze haslo jest wymagane - bez niego aplikacja odrzuci"
  echo "    kazde polaczenie (zasada: brak konfiguracji nie oznacza otwartych drzwi)."
  echo ""
  echo "    Docker Compose: wpisz APP_PASSWORD w pliku .env"
  echo "    Docker run:     dodaj -e APP_PASSWORD=twoje-haslo"
  exit 1
fi

# Bank zadań startowych musi być w katalogu danych, bo aplikacja czyta go
# stamtąd. Kopiujemy tylko raz - późniejsze zmiany użytkownika zostają.
if [ ! -f "$DATA_DIR/seed_tasks.json" ]; then
  mkdir -p "$DATA_DIR"
  cp "$SEED_SOURCE" "$DATA_DIR/seed_tasks.json"
  echo "[i] Skopiowano bank zadan do $DATA_DIR"
fi

# --no-access-log: nie zapisujemy adresów IP ani ścieżek żądań
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
