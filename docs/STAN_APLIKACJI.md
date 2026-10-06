# Stan aplikacji — Speaking Automaticity Trainer

*Dokument opisuje aktualny stan kodu w working tree (2026-09-03), nie stan ostatniego commita.*

> **Ważne:** repozytorium ma duże niezacommitowane zmiany. Cały stary model oparty
> na 8 modułach ćwiczeniowych ("drills") został w working tree usunięty i zastąpiony
> nowym modelem opartym o `Domain` / `SourcePack` i sesję wieloetapową. `README.md`,
> `SPEC.md` oraz `docs/JAK_TO_DZIALA.md` wciąż opisują **stary** model i są nieaktualne
> względem faktycznego kodu (`models.py`, `routers/speaking_sessions.py`,
> `SessionScreen.tsx`). `docs/URUCHOMIENIE.md` pozostaje aktualny (dotyczy instalacji,
> nie logiki ćwiczeń). Ten dokument opisuje kod, jaki jest teraz — jeżeli te zmiany
> zostaną zacommitowane, warto zaktualizować/zastąpić README i SPEC.
>
> **Etapy 1-3 przesunięcia w stronę "trenera automatyzacji produkcji mowy"** są
> wdrożone i opisane poniżej: Etap 1 (Keyword Planning, kompresja rund, rozdział
> Near/Far Transfer, migracja bazy), Etap 2 (Bottleneck Diagnostic A/B/C/D +
> opcjonalna kontrola native-language + Bottleneck Profile) i Etap 3 (rozbudowany
> Functional Chunk Bank wg kategorii komunikacyjnych, Recovery Drill, LLM
> follow-up). Świadomie odłożone (patrz sekcja "Poza zakresem" niżej): losowanie
> kolejności warunków A/B/C w diagnostyce, osobny tryb ćwiczenia chunków wg
> priorytetu z §5.2 specyfikacji, dalsze strojenie formuł `support.py` o sygnały
> diagnostyczne.

## Cel aplikacji

Trener automatyzmu mówienia po angielsku — lokalna aplikacja webowa (FastAPI + React),
jednoosobowa (jedno hasło, brak kont). Nagrywa wypowiedzi użytkownika, mierzy **metryki
czasowe płynności** (tempo, pauzy, długość ciągów mowy) zamiast oceniać poprawność
gramatyczną. Filozofia: nigdy nie poprawiać gramatyki w trakcie mówienia, brak
transkrypcji na żywo, metryki czasowe ważniejsze niż językowe. Osobny moduł: trener
tempa czytania (Reading Pace Trainer).

## Stos technologiczny

- **Backend:** FastAPI, SQLAlchemy 2.x, Pydantic 2.x, SQLite, spaCy (`en_core_web_sm`),
  ONNX Runtime (Silero VAD, CPU), OpenAI API (Whisper + LLM, domyślnie `gpt-4o-mini`),
  `wordfreq`.
- **Frontend:** React 18 + TypeScript, Vite, Tailwind, `onnxruntime-web` (VAD w
  przeglądarce), `recharts`. Brak routera — prosty automat stanów w `App.tsx`.
- **Wdrożenie:** Docker (multi-stage: pobranie modelu VAD → build frontendu → runtime
  Python 3.12-slim), `docker-compose.yml` (domyślnie tylko `127.0.0.1:8000`),
  `render.yaml`/`fly.toml` do hostingu, `setup.bat`/`start.bat` do uruchomienia lokalnego
  na Windows bez terminala.

## Architektura backendu

### `app/main.py`
Aplikacja FastAPI. Middleware `auth_gate`: fail-closed jeśli brak `APP_PASSWORD` i klient
nie jest lokalny; wymaga ciasteczka sesji dla ścieżek `/api/*` poza whitelistą
(`/api/auth/state`, `/api/auth/login`, `/api/auth/logout`, `/api/health`). Serwuje
zbudowany frontend (Vite `dist/`) z fallbackiem SPA. Rejestruje routery: `auth`,
`settings`, `calibrate`, `reading`, `stats`, `profile`, `speaking_sessions`.

### Model danych (`app/models.py`)

- **`User`** (jeden wiersz) — `noise_floor_db`, `vad_threshold` z kalibracji.
- **`AppSetting`** — klucz/wartość (klucz OpenAI, hash hasła), wartości w DB nadpisują env.
- **`ReadingAttempt`** — próby czytania; celowo osobna tabela od danych mowy spontanicznej
  (czytanie nie ma komponentu wyszukiwania leksykalnego, więc nie miesza się ze
  statystykami mowy).
- **`PersonalContext`** — wersjonowany wolny tekst o użytkowniku (praca, projekty,
  zainteresowania); edycje tworzą nowe wiersze, używany tylko najnowszy `active=True`.
- **`KnownVocabulary`** — biała lista lematów (top-3000 słów angielskich + opcjonalny
  import), używana do walidacji generowanych treści.
- **`Domain`** — jeden aktywny temat naraz, żyje przez `target_sessions` (domyślnie 5)
  sesji, status `active`/`done`.
- **`SourcePack`** — materiał na jedną sesję (generowany z wyprzedzeniem): `seed_text`,
  pytania naprowadzające, słowa kluczowe, `transfer_prompt`, status walidacji, powiązany
  z `Domain`.
- **`Chunk`** — fraza wielowyrazowa; `bank = 'domain'` (rotuje z `SourcePack`) lub
  `'function'` (stały zestaw ~20 fraz, generowany raz skryptem
  `scripts/seed_function_chunks.py`); pola harmonogramu w stylu SM-2 (`ease_factor`,
  `interval_sessions`, `next_due_session`, `consecutive_fast_exposures`).
- **`ChunkExposure`** — log jednej ekspozycji na chunk, `mode = 'access'` (Faza 2A) lub
  `'embed'` (Faza 2B), czas reakcji, flaga ciszy, sukces.
- **`SpeakingSession`** — jeden "blok": jeden `SourcePack` powtarzany w 4 rundach
  głównych; poziom wsparcia na starcie, powód przerwania, ukończone fazy.
- **`Round`** — jedna z 4 powtórek bloku głównego: numer 1–4, poziom wsparcia 0–4, czas
  przygotowania, limit mówienia.
- **`TransferProbe`** — Faza 4, **jedyny prawdziwy pomiar postępu**; od Etapu 1
  rozdzielona na `probe_type = 'near' | 'far' | 'legacy'` (do dwóch wierszy na
  sesję, unikalność złożona `(session_id, probe_type)`), z polami `prompt` (treść
  faktycznie zadanego pytania) i `order_in_session`. Wynik `answered`/`redirected`/
  `stalled` klasyfikowany przez LLM (odpowiedź i przekierowanie liczą się jako
  sukces, tylko `stalled` jest negatywne). Wiersze sprzed rozdziału mają
  `probe_type='legacy'` (migracja, patrz `app/migrations.py`).
- **`Attempt`** — jedna nagrana próba, powiązana z dokładnie jednym z: `round_id`,
  `chunk_exposure_id`, `transfer_probe_id`, `diagnostic_trial_id` *(Etap 2)*,
  `recovery_attempt_id` *(Etap 3)*; audio kasowane po analizie, poza Rundą 1
  (trzymana 24h dla ćwiczenia autotranskrypcji).
- **`FluencyMetrics`** — metryki jednej próby: tempo artykulacji, średnia długość ciągu
  mowy, wskaźnik fonacji, czas trwania i częstość pauz (środek klauzy vs. koniec
  klauzy), częstość wypełniaczy (tylko opisowo, nigdy nie karana), czas do pierwszego
  słowa, pewność segmentacji klauzul, plus JSON `extra`.
- **`Baseline`** — stara krocząca mediana (okno 10) per metryka, z sond transferu
  **sprzed rozdziału Near/Far. Zamrożona od Etapu 1** — nowy kod jej nie czyta ani
  nie zapisuje (żeby nie zmieszać starego baseline'u z nowymi seriami), zostaje
  wyłącznie żeby nie tracić historii.
- **`TransferBaseline`** *(nowe, Etap 1)* — następca `Baseline`: krocząca mediana
  (okno 10) per `(metric_name, probe_type)`, osobno dla `near` i `far`. Sondy
  `legacy` do niej nie trafiają.
- **`KeywordPlan`** *(nowe, Etap 1)* — plan hasłowy zapisany przed blokiem rund:
  do 3 haseł (`items`, max 5 słów każde, walidacja w routerze), `planning_seconds`
  wg poziomu wsparcia na starcie sesji.
- **`WritingRehearsal`** — pełne pisanie przed mówieniem; **od Etapu 1 to już nie
  domyślny scaffold**, tylko opcjonalny "rescue mode" dostępny z ekranu Keyword
  Planning gdy poziom wsparcia na starcie ≥ 3 (model/endpoint bez zmian, zmieniło
  się tylko to, kto go wywołuje).
- **`SelfTranscription`** — opcjonalne zadanie po sesji: własna transkrypcja z pamięci
  Rundy 1 vs. transkrypcja Whisper, wyłącznie introspekcyjne, nigdy nie oceniane.
- **`SupportEvent`** — historia zmian poziomu wsparcia z uzasadnieniem.

`SpeakingSession` ma od Etapu 1 dwa dodatkowe pola: `far_transfer_prompt` (pytanie
"far" wygenerowane best-effort przy starcie sesji, `None` gdy LLM wyłączony/
zawiódł — wtedy frontend pomija ten krok) i `transfer_order` (lista `["near","far"]`
w losowej kolejności, ustalona raz przy starcie i trzymana niezmiennie).

### Routery

- **`auth.py`** (`/api/auth`) — logowanie jednym hasłem (bez kont): `GET /state`,
  `POST /login` (ciasteczko HMAC, 30 dni), `POST /logout`.
- **`settings.py`** (`/api/settings`) — klucz OpenAI (walidowany na żywo przy zapisie),
  hasło instancji (min. 8 znaków, wymaga obecnego hasła przy zmianie), nazwa modelu LLM.
- **`calibrate.py`** (`/api`) — 10 s nagrania ciszy → poziom szumu (dB) + próg VAD,
  zapisywane w `User`.
- **`reading.py`** (`/api/reading`) — trener tempa czytania (patrz niżej).
- **`profile.py`** (`/api/profile`) — CRUD dla `PersonalContext` i `Domain` (10 gotowych
  sugestii tematów, tworzenie/kończenie/wznawianie).
- **`stats.py`** (`/api/stats`) — `GET /progress?days=&probe_type=far|near|legacy`
  (domyślnie `far`) — wyłącznie metryki z sond transferu danego typu, agregowane
  jako dzienne mediany 4 metryk (celowo pomija dane rund/chunków).
- **`speaking_sessions.py`** (`/api/speaking-sessions`) — silnik sesji (patrz niżej):
  `start`, `get`, `status`, `writing-rehearsal` (rescue mode), `keyword-plan`
  *(nowe, Etap 1)*, `rounds/{n}/attempts`, `transfer-probe/{near|far}` *(od Etapu 1
  sparametryzowane typem sondy zamiast jednego endpointu)*, `attempts/{id}` (poll),
  `chunks/{id}/access`, `chunks/{id}/embed`, `self-transcription` (+ `available`), `end`.

### Kluczowe serwisy (`app/services/*.py`)

- **`pack_gen.py`** — generuje `SourcePack` przez LLM z `PersonalContext` + `Domain` +
  `KnownVocabulary` + chunków z poprzednich sesji; waliduje słownictwo, ogranicza typ
  zadania, odrzuca i regeneruje przy błędzie (do 5 prób).
- **`support.py`** — algorytm adaptacyjnego poziomu wsparcia (0–4): pierwsze 3 sesje na
  poziomie 4 (kalibracja); degradacja wymaga 3 z 4 ostatnich sesji spełniających
  kryteria pauz/MLR względem baseline; awans wymaga 2 z 2 z niską fonacją lub niskim
  wykorzystaniem czasu; `should_interrupt_session()` przerywa sesję wcześniej, jeśli
  fonacja w Rundzie 3 spadnie poniżej 60% Rundy 1. Od Etapu 1 `get_baseline_median`/
  `push_baseline_value` operują na `TransferBaseline` per `probe_type` (domyślnie
  `"far"`) zamiast na starej `Baseline`; reguły degradacji/awansu patrzą wyłącznie na
  sondę **far** danej sesji (far jest głównym sygnałem generalizacji automatyzmu),
  same formuły progów bez zmian.
- **`chunk_scheduler.py`** — obsługa Banku A (chunki domenowe) i Banku B (stałe ~20 fraz
  funkcyjnych, harmonogram SM-2-podobny wg czasu reakcji); sukces trybu "embed" =
  rozpoczęcie mówienia <1,5 s i brak przerwy >2 s (treść nieoceniana).
- **`domains.py`** — pobranie aktywnej domeny, inkrementacja licznika sesji, automatyczne
  zamknięcie domeny po `target_sessions`.
- **`transfer_probe.py`** — klasyfikacja wyniku sondy transferu (reguła twarda:
  fonacja < 0,5 → `stalled`; inaczej LLM klasyfikuje `answered`/`redirected`/`stalled`).
  Od Etapu 1 też `generate_far_transfer_prompt()`: pytanie "far" generowane best-effort
  przez LLM na bazie wyłącznie `PersonalContext` — świadomie **nie** korzysta z
  aktywnej `Domain`/`SourcePack`, żeby mierzyć generalizację poza wytrenowany temat;
  `None` przy LLM wyłączonym/błędzie, sesja mimo to startuje.
- **`attempt_pipeline.py`** — pipeline tła dla każdej próby: WAV → segmenty VAD →
  (jeśli fonacja ≥ 0,3 s) transkrypcja Whisper → dopasowanie interpunkcji → granice
  klauzul → metryki czasowe i językowe → zapis `FluencyMetrics`; audio kasowane od razu
  poza Rundą 1.
- **`metrics.py`** — silnik metryk czasowych (na bazie segmentów VAD, nie znaczników
  Whisper): czas do pierwszego słowa, wskaźnik fonacji, tempo mowy/artykulacji, średnia
  i maks. długość ciągu, liczba i długość pauz, klasyfikacja pauz środek/koniec klauzuli,
  liczba/częstość wypełniaczy, oś czasu fonacji w binach 5-sekundowych.
- **`lang_metrics.py`** — powtórzenia n-gramowe, fałszywe starty, markery naprawy, MTLD
  (różnorodność leksykalna), profil słownictwa poza top-2000, długość zdań, indeks
  podrzędności (spaCy), heurystyka granic klauzul, dystans leksykalny (Jaccard).
- **`llm.py`** — wrapper OpenAI chat completions (`response_format: json_object`),
  walidacja Pydantic, prompty w `app/prompts/*.md`.
- **`transcription.py`** — wrapper Whisper (`verbose_json`, znaczniki słów/segmentów,
  `temperature=0`, prompt zapobiegający "wygładzaniu" dysfluencji, poza trenerem czytania
  gdzie prompt jest pusty celowo).
- **`vad.py`** — Silero VAD po stronie serwera (ONNX, CPU), kalibracja progu z 99.
  percentyla prawdopodobieństwa mowy na próbce ciszy.
- **`reading.py`** — silnik wyrównania trenera czytania (patrz niżej).
- **`retention.py`** — sprzątanie audio starszego niż `AUDIO_RETENTION_DAYS` (domyślnie
  30 dni) — siatka bezpieczeństwa na wypadek przerwanego przetwarzania.
- **`seed.py`** — ładuje `data/language_config.json` (wypełniacze, markery naprawy, progi
  pauz, prompt Whisper, 21 opisów struktur gramatycznych używanych tylko w generatorze
  tekstów do czytania); zasiewa `User(id=1)` i `KnownVocabulary`.

### Konfiguracja (`app/config.py`)

Zmienne env (`.env`): `openai_api_key`, `openai_llm_model` (domyślnie `gpt-4o-mini`),
`app_password` (puste = tylko localhost), `mock_transcription`, `data_dir`, `web_dist`,
`audio_retention_days` (30).

### Migracje (`app/migrations.py`, nowe, Etap 1)

Repo nie używa Alembic. `init_db()` (`app/db.py`) woła `run_migrations(engine)`
**przed** `Base.metadata.create_all()` — idempotentne, oparte o `PRAGMA table_info`:
dodaje brakujące kolumny (`speaking_sessions.far_transfer_prompt`/`transfer_order`)
i przebudowuje `transfer_probes` (zmiana unikalności `session_id` →
`(session_id, probe_type)`), oznaczając wszystkie wiersze sprzed zmiany jako
`probe_type='legacy'`. Bez tego mechanizmu istniejący plik `data/app.db` użytkownika
nigdy nie dostałby nowego kształtu tabel — `create_all` tworzy tylko brakujące tabele,
nie zmienia istniejących. Testy w `tests/test_migrations.py`.

## Model sesji (rdzeń aplikacji)

Jedna `Domain` (np. "praca zdalna") jest aktywna naraz i "przeżywana" przez ok. 5–7
sesji. Każda sesja (`POST /api/speaking-sessions/start`) pobiera lub generuje
niewykorzystany, zwalidowany `SourcePack` dla tej domeny, generuje best-effort pytanie
"far transfer" i losuje kolejność Near/Far, po czym przechodzi przez fazy:

1. **Faza 0 — Rozgrzewka czytaniem** (`ReadingWarmup`): jednorazowe głośne przeczytanie
   `seed_text`, zgłaszane przez zwykły endpoint `/api/reading` (poza statystykami mowy
   spontanicznej).
2. **Faza 1 — Wejście** (`EntryPhase`): ciche ponowne przeczytanie `seed_text` + pytań
   naprowadzających, bez nagrywania.
3. **Faza 2A — Ćwiczenie chunków, Bank A** (`ChunkDrillA`): chunki domenowe i funkcyjne
   pokazywane jako polskie podpowiedzi (`prompt_pl`), użytkownik mówi frazę na głos,
   mierzony jest tylko czas reakcji, audio nie jest zachowywane.
4. **Faza 2B — Chunki, Bank B / tryb "embed"** (`ChunkDrillB`, odblokowywana od sesji 4,
   tylko gdy istnieją chunki Banku B): trzeba zacząć nagranie od docelowej frazy i mówić
   dalej ~10 s; sukces = start <1,5 s i brak przerwy >2 s (treść nieoceniana).
5. **Keyword Planning** *(nowe, Etap 1 — zastępuje automatyczną fazę pisania)*
   (`KeywordPlanningPhase`): do 3 krótkich haseł (max 5 słów każde), bez pełnego
   edytora tekstu; czas na zapisanie ich maleje z poziomem wsparcia startowego
   (`KEYWORD_PLANNING_S = {4:45, 3:30, 2:15, 1:5, 0:0}` s) — przy wsparciu 0 faza
   jest w ogóle pomijana. Zapisany plan jest potem przypominany w każdej rundzie.
   Pełne pisanie (`WritingRehearsal`) zostaje jako opcjonalny "rescue mode" — przycisk
   "Need more time? Write it out first", widoczny tylko gdy startowy poziom wsparcia
   ≥ 3, otwiera dotychczasowy ekran wolnego pisania zamiast list haseł.
6. **Blok główny, 4 rundy — kompresja pomysłu** (`RoundPhase`): ten sam `SourcePack`
   wypowiadany 4 razy przy malejącym poziomie wsparcia (od poziomu startowego do 0)
   i zmiennym czasie przygotowania, ale **od Etapu 1 ze stałym, krótszym harmonogramem
   czasu mówienia dla każdej rundy: 90 / 75 / 60 / 45 s** (`COMPRESSION_SPEAK_S`,
   ten sam dla wszystkich poziomów wsparcia — zastąpił stare 180 s / malejący
   180‑135‑105‑90 s). Przed każdą rundą pokazywany jest komunikat instruujący do
   kompresji tej samej myśli w krótszym czasie (np. Runda 3: "Keep only the main
   point, one example, and maybe one caveat"), nie do mówienia szybciej. Widoczna
   treść wsparcia bez zmian: ≥4 pełny `seed_text`, ≥3 pytania naprowadzające, ≥2
   słowa kluczowe, ≤1 tylko nazwa tematu. Po Rundzie 3 serwer sprawdza
   `should_interrupt_session` (spadek fonacji poniżej 60% Rundy 1) i może przerwać
   sesję od razu do podsumowania — zabezpieczenie przed zmęczeniem poznawczym.
7. **Near Transfer i Far Transfer** *(od Etapu 1 dwie osobne sondy zamiast jednej)*
   (`TransferPhase`, po 120 s, bez przygotowania, bez wsparcia, w losowej kolejności
   ustalonej przy starcie sesji): **Near** odpowiada na `SourcePack.transfer_prompt`
   (nowe pytanie, ale w tej samej domenie — jak dawna, jedyna sonda). **Far**
   odpowiada na pytanie z zupełnie innego obszaru, wygenerowane bez udziału aktywnej
   `Domain` (`generate_far_transfer_prompt`) — mierzy generalizację automatyzmu poza
   wytrenowany temat i jest pomijane, jeśli generacja się nie powiodła. Metryki
   każdej sondy zasilają własny, osobny `TransferBaseline` (`near`/`far` nigdy się
   nie mieszają); **far jest głównym KPI** używanym przez `/api/stats/progress`
   (domyślny filtr) i przez reguły adaptacyjnego wsparcia w `support.py`. Obie
   sondy klasyfikowane post-hoc jako answered/redirected/stalled.

Po `POST /{id}/end`: inkrementacja licznika sesji domeny (auto-zamknięcie po
`target_sessions`), ewaluacja i ewentualna zmiana poziomu wsparcia
(`support.evaluate_and_apply`, na bazie sondy **far**), aktualizacja harmonogramów
chunków Banku B, obliczenie delt metryk względem baseline **osobno dla near i far**
do ekranu podsumowania, ewentualne generowanie w tle kolejnego `SourcePack`.
Opcjonalne ćwiczenie **autotranskrypcji** (porównanie własnej pamięci Rundy 1 z
transkrypcją Whisper) dostępne przez 24h.

## Trener tempa czytania (osobny moduł)

Pełny, niezależny moduł (`ReadingAttempt`, router `/api/reading`, serwis `reading.py`),
celowo odseparowany od statystyk mowy spontanicznej.

- **Nagrywanie i analiza**: wklejenie lub wygenerowanie tekstu, ustawienie tempa
  docelowego (60–300 wpm), czytanie na głos; audio przetwarzane w pliku tymczasowym i
  natychmiast kasowane. Whisper wywoływany z **pustym** promptem (bez podpowiedzi
  tekstu), żeby nie "podpowiadał" sobie referencji.
- **Wyrównanie**: `difflib.SequenceMatcher` między tekstem referencyjnym a rozpoznaną
  mową → status każdego słowa: wypowiedziane / niejasne / pominięte.
- **Metryki**: wpm brutto, wpm artykulacji (tylko czas fonacji), odchylenie od celu,
  stabilność (odchylenie standardowe lokalnego tempa w oknie 5 słów), najszybsze/
  najwolniejsze fragmenty, dokładność, liczba i długość pauz (próg ≥0,35 s).
- **Generowanie tekstu** (`POST /api/reading/generate`): LLM tworzy tekst o długości
  `minuty × tempo_docelowe` słów, na wybrany temat, opcjonalnie wplatając do 3 struktur
  gramatycznych (z listy 21, czysto opisowych, bez detekcji). Ostrzeżenie, jeśli tekst
  zawiera cyfry (Whisper zapisuje liczby słownie, co psuje dopasowanie).
  Selektor struktur w UI domyślnie rozwinięty (ostatnia zmiana:
  "Wybor struktur w generatorze widoczny od razu").
- **Mapa prędkości (UI)**: każde słowo podświetlone od niebieskiego (wolniej) do
  czerwonego (szybciej) względem tempa docelowego, zawsze z liczbową legendą.

## Bottleneck Diagnostic (Etap 2, osobny moduł)

Sprawdza, czy koszt spontanicznej wypowiedzi leży głównie w wymyślaniu treści,
formulacji językowej, czy w braku przygotowania — świadomie **osobny** od
`SpeakingSession`, nigdy nie zasila `/api/stats/progress` ani żadnego `Baseline`.

- **Model** (`models.py`): `DiagnosticSession` (status `in_progress`/`completed`,
  `language_control_enabled`), `DiagnosticTrial` (`condition` = `cold` /
  `supplied_ideas` / `self_plan` / `repetition` / `native_control`, `prompt`,
  `support_json`, `planning_seconds`, `speaking_limit_seconds`, `source_trial_id`
  dla `repetition` wskazujący na `self_plan`).
- **Generator** (`services/diagnostics.py::_generate_prompt_set`, prompt
  `app/prompts/diagnostic_prompt_set.md`): jedno wywołanie LLM tworzy **matched
  prompt set** — cztery różne pytania o tym samym poziomie trudności (plus
  pytanie po polsku dla kontroli), walidowane wobec `KnownVocabulary` (reużycie
  `pack_gen.unknown_words`), do 3 prób.
- **Router** `app/routers/diagnostics.py` (`/api/diagnostics`): `start`
  (generuje sesję + trials A→B→C→D[→native]), `GET /{id}` (bez interpretacji,
  dopóki `status != completed`), `POST /{id}/plan` (hasła do `self_plan`, te
  same limity co Keyword Planning z Etapu 1 — przeniesione do
  `services/constants.py`), `POST /{id}/trials/{condition}/attempts` (202,
  `native_control` woła `attempt_pipeline.process_attempt(..., skip_language_metrics=True)`
  — pomija spaCy/`lang_metrics`, bo zakładają angielski), `GET
  attempts/{id}` (poll), `POST /{id}/end`, `GET /profile`.
- **Interpretacja** (`diagnostics.session_note`): warstwa heurystyczna, neutralny
  język (np. "Wsparcie w wyborze treści wyraźnie poprawia płynność..."), pokazywana
  dopiero **po zakończeniu** całej sesji (żeby nie wpływać na kolejne próby),
  zawsze z zastrzeżeniem o wiarygodności poniżej 3 sesji.
- **Bottleneck Profile** (`diagnostics.bottleneck_profile`): dostępny po ≥3
  ukończonych sesjach diagnostycznych, agreguje mediany `phonation_time_ratio`
  po warunku i zwraca wyłącznie etykiety `high`/`medium`/`low`/`unclear` dla 5
  wymiarów (content generation sensitivity, planning benefit, repetition
  benefit, L2-specific cost, sustained-speech cost — to ostatnie reużywa dane
  Runda 1 vs Runda 4 ze zwykłych `SpeakingSession`, bez nowej tabeli), zawsze z
  disclaimerem "to profil treningowy... nie diagnoza medyczna ani psychologiczna".
- **Frontend**: `DiagnosticScreen.tsx` (jeden trial na ekran, `self_plan` z
  własnym UI haseł), `BottleneckProfileScreen.tsx`. Dostępne z `StartScreen`
  ("Bottleneck diagnostic" + checkbox "also include one question in Polish").

## Recovery Drill (Etap 3, osobny moduł)

Krótki trening odzyskiwania kontroli nad wypowiedzią po zgubieniu wątku — treść
nigdy nie jest oceniana, mierzone są tylko standardowe metryki czasowe.

- **Model**: `RecoveryAttempt` (`kind` = `lost_thread` / `reformulation` /
  `clarification_followup`, `prompt`, `follow_up_question`). Bez osobnej tabeli
  "sesji" — trzy próby bez wspólnego rodzica w bazie, jak `WritingRehearsal`.
- **Serwis** `services/recovery.py`: `lost_thread`/`reformulation` mają statyczny
  prompt (bez LLM) + opcjonalną podpowiedź chunku z odpowiedniej kategorii Banku
  B (`returning_to_thread` / `repair_reformulation`); `clarification_followup`
  generowany dopiero po `lost_thread` (`generate_follow_up`, prompt
  `app/prompts/recovery_followup.md`, schemat z **jednym polem** `question` —
  fizycznie nie da się zwrócić feedbacku), z zapasowym pytaniem gdy LLM
  wyłączony.
- **Router** `app/routers/recovery.py` (`/api/recovery`): `GET
  trials/{kind}`, `POST trials/{kind}/attempts` (202), `POST /follow-up`
  (generuje pytanie na bazie transkrypcji `lost_thread`), `POST
  follow-up/{recovery_attempt_id}/attempts` (202), `GET attempts/{id}`.
- **Frontend**: `RecoveryDrillScreen.tsx` — 3 kroki sekwencyjnie, zero liczb
  pokazywanych użytkownikowi. Dostępny z `StartScreen` ("Recovery drill").

## Rozszerzony Functional Chunk Bank (Etap 3)

Bank B (`Chunk.bank='function'`) ma teraz **7 kategorii komunikacyjnych**
zamiast poprzednich 5: `starting_stance`, `structuring`, `example`,
`contrast_qualification`, `repair_reformulation`, `returning_to_thread`,
`buying_planning_time` (`app/prompts/generate_function_chunks.md`,
`scripts/seed_function_chunks.py::CATEGORIES`). Wymaga ponownego uruchomienia
`seed_function_chunks.py --force`, żeby zastąpić stary zestaw. W `SessionScreen.tsx`
`RoundPhase` pokazuje teraz do 2 losowych chunków jako nieobowiązkowe "available
tools" przy `support_level <= 2` (tekstowe wsparcie już zredukowane). Scheduler
(`chunk_scheduler.py`) bez zmian — pozostaje kategorio-agnostyczny (SM-2-podobny
wg czasu reakcji).

## Frontend — ekrany (`apps/web/src/`)

Automat stanów bez routera (`App.tsx`): `loading → login → start`, z `start` dostępne
`session`, `calibrate`, `settings`, `profile`, `reading`, `progress`, `diagnostic`,
`bottleneckProfile`, `recoveryDrill`; `session → sessionSummary → selfTranscription`
(opcjonalnie); `diagnostic → diagnosticNote`.

- **`LoginScreen`** — jedno pole hasła.
- **`StartScreen`** — hub: ostrzeżenie o braku klucza OpenAI, przycisk "Kalibruj" jeśli
  brak kalibracji, inaczej "Rozpocznij sesję" + "Trener tempa czytania" + "Recovery
  drill" + "Bottleneck diagnostic" (z checkboxem kontroli po polsku) + linki do
  profilu/postępu/**profilu wąskiego gardła**/ustawień/rekalibracji.
- **`CalibrationScreen`** — 10 s ciszy → wynik kalibracji.
- **`ProfileScreen`** — edycja `PersonalContext` i zarządzanie aktywną `Domain`
  (utworzenie/wybór z 10 sugestii/zakończenie/wznowienie).
- **`SettingsScreen`** — klucz OpenAI (walidacja na żywo), hasło instancji, wylogowanie.
- **`SessionScreen`** — silnik sesji, dynamiczna lista kroków budowana z `SessionPack`
  zwróconego przez `/start`. Od Etapu 1: krok `keywordPlanning` (hasła + rescue mode do
  pełnego pisania) zamiast automatycznego `writingRehearsal`; dwa kroki `transfer` (near
  i far) w kolejności `pack.transfer_order`, z far pomijanym gdy `far_transfer_prompt`
  jest `null`; w rundach dodatkowy komunikat kompresji i przypomnienie zapisanego planu.
- **`SessionSummaryScreen`** — powód zakończenia (ukończona / przerwana wcześniej),
  **osobne sekcje "Near transfer" i "Far transfer"** *(Etap 1, zamiast jednej płaskiej
  sekcji)*, każda z notatką o wyniku i deltami względem własnej mediany kroczącej (3
  metryki, celowo bez z-score'ów/ocen), aktualny poziom wsparcia i czy się zmienił, link
  do autotranskrypcji.
- **`SelfTranscriptionScreen`** — porównanie własnej pamięci Rundy 1 z transkrypcją
  Whisper, wyłącznie introspekcyjne.
- **`ProgressScreen`** — wykresy liniowe (recharts, ostatnie 90 dni) 4 metryk z sond
  transferu, **z przełącznikiem Far / Near / Legacy** *(Etap 1, domyślnie Far — główny
  KPI generalizacji)*.
- **`ReadingScreen`** — pełne UI trenera czytania: konfiguracja, nagrywanie ze
  wskaźnikiem VAD w przeglądarce, mapa prędkości, metryki liczbowe.

## Co zostało usunięte (stary model, w working tree)

Routery: `sessions.py`, `attempts.py`, `tasks.py`, `learning_sessions.py`.
Serwisy: `drills.py`, `adaptation.py`, `task_gen.py`, `task_select.py`, `structures.py`,
`structure_mode.py`, `forbidden.py`, `indices.py`, `pipeline.py`.
Definicje ćwiczeń (`app/drills/*.json`): Rapid Response, Unexpected Questions, Fluency
Sprint, Describe Without the Word, Paraphrase, Simplify, Idea Expansion, Story Loop.
Frontend: `SessionHub.tsx`, `DrillScreen.tsx`, `ObservationsScreen.tsx`,
`StructuresScreen.tsx`.

Ten model (8 osobnych "drilli" wybieranych z puli zadań, z systemem indeksów trudności i
filtrem struktur gramatycznych) opisują wciąż `README.md`, `SPEC.md` i
`docs/JAK_TO_DZIALA.md` — te dokumenty wymagają aktualizacji, jeśli obecne zmiany
zostaną zacommitowane.
