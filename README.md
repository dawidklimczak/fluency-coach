# Speaking Automaticity Trainer

Trenażer automatyzacji mowy angielskiej (spec: `SPEC.md`). Cel: skrócić czas od
intencji do wypowiedzi i wydłużyć nieprzerwane odcinki mowy - nie poprawiać
gramatykę. Feedback zawsze po fakcie, metryki czasowe z serwerowego VAD.

Zrealizowany zakres: **Faza 1 + Faza 2** (pipeline audio, kalibracja, VAD,
Whisper z zachowaniem dysfluencji, silnik metryk, maszyna drilli, moduły
Rapid Response / Describe Without the Word / Fluency Sprint, feedback,
podsumowanie sesji, adaptacja trudności).

## Stack

- `apps/web` - React + Vite + TypeScript + Tailwind, Silero VAD w przeglądarce
  (onnxruntime-web) tylko do wskaźnika mowy i auto-stopu
- `apps/api` - FastAPI (Python 3.11+), Silero VAD na CPU jako źródło prawdy,
  Whisper API (`whisper-1`), SQLite w `data/app.db`
- audio: WAV PCM 16-bit mono 16 kHz, nagrania w `data/audio/`

## Pierwsze uruchomienie

```powershell
# 1. Model VAD (ok. 1.8 MB, do backendu i frontendu)
python scripts\download_models.py

# 2. Backend
cd apps\api
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 3. Frontend
cd ..\web
npm install

# 4. Klucze API
# skopiuj .env.example do .env w katalogu głównym i uzupełnij OPENAI_API_KEY
# (klucz może też być w zmiennych środowiskowych systemu)
```

## Start

Dwa terminale:

```powershell
# backend (http://127.0.0.1:8000)
cd apps\api
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# frontend (http://localhost:5173, proxy /api -> backend)
cd apps\web
npm run dev
```

Przy pierwszym wejściu aplikacja wymaga kalibracji: 10 s ciszy w Twoim
pomieszczeniu (koryguje próg VAD pod szum tła).

## Testy krytyczne (SPEC sekcja 13)

```powershell
cd apps\api
.venv\Scripts\python -m pytest tests -v
```

- `test_vad_timing.py` - dokładność ttfw (2.0 s ± 100 ms) i pauz o znanej długości
- `test_calibration.py` - stabilność liczby pauz przy 3 poziomach szumu
- `test_disfluency.py` - Whisper zachowuje >= 80% wypełniaczy i powtórzeń
  (wywołuje prawdziwe API; pomijany bez `OPENAI_API_KEY`)
- `test_metrics.py` - silnik metryk na danych syntetycznych

Fixtury audio generują się automatycznie przez Windows TTS (SAPI) przy pierwszym
uruchomieniu testów.

## Czego celowo nie ma (non-goals ze spec)

Korekty gramatycznej w trakcie mówienia, transkrypcji na żywo, oceny poprawności
jako wyniku, fiszek i nauki słownictwa. Podczas nagrywania na ekranie jest
wyłącznie: bodziec, timer i pasek "mówisz / cisza".

## Jeszcze niezaimplementowane (Faza 3)

Pełne metryki językowe (MTLD, subordination_index), wskaźnik
`complexity_fluency_tradeoff`, ekran postępu i mapa cieplna struktur
gramatycznych, detekcja struktur spaCy, generowanie zadań i ocena jakościowa
przez LLM (Anthropic), pozostałe 7 modułów drilli, obserwacje tygodniowe,
retencja audio 30 dni. Endpointy `stats/structures` i `tasks/generate` dojdą
z tą fazą.
