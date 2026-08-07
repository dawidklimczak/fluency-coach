# Speaking Automaticity Trainer

A speaking trainer for people whose English comprehension runs far ahead of their
production. It does not teach grammar or vocabulary. It measures how long it takes
you to start speaking, how long you speak without stopping, and where your pauses
fall — then trains those numbers down under time pressure.

**The core idea:** a grammar mistake made during fluent speech is a success. Hesitating
while you assemble a perfect sentence is the failure. The app is built around that
inversion, and it never corrects you mid-sentence.

> **Nietechniczny użytkownik?** Zobacz [docs/URUCHOMIENIE.md](docs/URUCHOMIENIE.md) —
> instrukcja krok po kroku po polsku, bez terminala.

## What it measures

Timing metrics come from server-side Silero VAD, never from the browser and never
from transcript timestamps:

- **time to first word** — from stimulus to your first sound
- **mean length of run** — words spoken between pauses ≥ 250 ms
- **mid-clause pause ratio** — pauses inside a phrase signal retrieval trouble;
  pauses at sentence boundaries are normal and are counted separately
- **phonation time ratio**, articulation rate, long-pause count

Language metrics come from the transcript (Whisper, configured to *preserve*
disfluencies rather than clean them up): filler rate, repairs, repetitions, MTLD,
subordination index, and a frequency profile.

A grammatical-structure subsystem detects 21 target structures with spaCy and
reports **avoidance** — whether you reached for the third conditional or quietly
routed around it. Avoidance in implicit mode versus explicit mode is the main
diagnostic output.

## Modules

Rapid Response · Unexpected Questions · Fluency Sprint · Describe Without the Word ·
Paraphrase · Simplify · Idea Expansion · Story Loop

All eight are one state machine with different JSON configuration in
`apps/api/app/drills/`.

### Reading pace trainer

A separate tool: paste any text, set a target pace, read it aloud. You get your
overall words-per-minute (gross and excluding pauses), a steadiness figure, and a
**speed map** — the text re-rendered with each word tinted by its local pace
relative to your target, so you can see where you rush and where you stall.

Reference text and transcript are aligned with `difflib`, which also surfaces
skipped words and words that came through as something else — a cheap proxy for
unclear articulation, though it also catches plain transcription errors, so it is
presented as "did not come through", never as a pronunciation verdict.

Reading aloud has no lexical-retrieval component, so these attempts are stored
separately and **never** enter the spontaneous-speech statistics: they cannot skew
z-scores, difficulty adaptation, or the structure heat map. Recordings here are
processed in a temporary file and deleted immediately.

## How a session works

You open a **learning session**, run as many drills inside it as you like, then close
it. Closing produces a summary plus constructive feedback — including recurring
grammar patterns from that session, which is the only place grammar is ever mentioned.
Those patterns feed **Observations**: a running diagnosis rebuilt after every session,
showing what you get wrong most often and which patterns persist across weeks.

## Running it

You need an OpenAI API key. Transcription uses `whisper-1`; feedback and task
generation use a chat model (default `gpt-4o-mini`). Timing metrics work without a
key, but you get no transcript and no feedback. See
[docs/URUCHOMIENIE.md](docs/URUCHOMIENIE.md) for cost estimates.

### Docker (recommended)

```bash
cp .env.example .env      # set APP_PASSWORD, optionally OPENAI_API_KEY
docker compose up -d
```

Open <http://127.0.0.1:8000>. Data lives in the `trainer-data` volume.

A password is **required** in Docker: container traffic arrives via the Docker
gateway, so the app cannot recognise it as local and refuses to serve without one.

### From source

```bash
python -m venv apps/api/.venv
apps/api/.venv/bin/pip install -r apps/api/requirements.txt
apps/api/.venv/bin/python -m spacy download en_core_web_sm
apps/api/.venv/bin/python scripts/download_models.py
cd apps/web && npm install && npm run build && cd ../..
apps/api/.venv/bin/python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

On Windows: run `setup.bat` once, then `start.bat`.

### Development

Backend and Vite dev server separately, with hot reload:

```bash
cd apps/api && .venv/bin/python -m uvicorn app.main:app --reload    # :8000
cd apps/web && npm run dev                                          # :5173, proxies /api
```

Tests: `cd apps/api && .venv/bin/python -m pytest tests -q`. They run against a
temporary data directory and never touch your real database. `tests/test_disfluency.py`
calls the real Whisper API and needs a key.

## Hosting

The app is **single-user by design** — there are no accounts, and all history belongs
to one person. Host one instance per person, not one instance for many.

`render.yaml` and `fly.toml` are ready to use; both mount a persistent disk at `/data`
and ask for `APP_PASSWORD` before the service goes live. Plan for **at least 1 GB RAM**
— spaCy, onnxruntime and numpy need roughly 500–700 MB resident.

## Security model

- **Fail closed.** With no password set, the app serves only `localhost`. Reached from
  anywhere else it returns 503 on every path rather than opening up.
- The password is set via `APP_PASSWORD` before first start, and can be changed later
  in Settings without a redeploy. Stored as an scrypt hash.
- The OpenAI key is stored on your instance, never returned to the browser in full
  (only a masked hint), and is sent only to OpenAI.
- Access logging is disabled in the container image; no IP addresses are recorded.

## Privacy

Everything stays on the machine that runs the app: SQLite database, WAV recordings,
transcripts and metrics. Audio is deleted after 30 days by default
(`AUDIO_RETENTION_DAYS`); metrics are kept. Audio and transcripts go to OpenAI for
transcription and feedback — that is the only outbound traffic.

## Specification

[SPEC.md](SPEC.md) is the original design document: the theoretical model, formal
metric definitions, the drill contract, and the deliberate non-goals. Read section 2
before changing behaviour — several apparent bugs are decisions.

## License

MIT. The Silero VAD model is downloaded at setup time from its own repository under
its own license.
