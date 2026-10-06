# Speaking Automaticity Trainer - specyfikacja

Dokument wejściowy dla Claude Code. Stack ustalony: React (Vite + TypeScript) + FastAPI (Python 3.11+) + SQLite. Transkrypcja: OpenAI Whisper API. Bez GPU.

---

## 1. Problem i cel

Użytkownik docelowy ma rozumienie na poziomie C1+, ale produkcja mowy zawodzi. Objawy, które aplikacja ma mierzyć i redukować:

- blokada leksykalna pod presją czasu (znane słowo nie wydobywa się w czasie rzeczywistym),
- nadmierna złożoność składniowa - użytkownik buduje zdanie, którego nie potrafi dokończyć,
- świadome monitorowanie gramatyki w trakcie mówienia (kontrola zamiast automatyzmu),
- zmęczenie poznawcze po ~60 minutach konwersacji.

To nie jest problem wiedzy. To problem dostępu do wiedzy pod ograniczeniem czasu. Model teoretyczny: Levelt - konceptualizacja, formułowanie, artykulacja. U tego użytkownika formułowanie nie jest zautomatyzowane i konkuruje o pamięć roboczą z monitorowaniem.

**Cel aplikacji: skrócić czas od intencji do wypowiedzi i wydłużyć nieprzerwane odcinki mowy. Nie: poprawić gramatykę.**

### Non-goals (twarde)

- Nie ma korekty gramatycznej w trakcie mówienia. Nigdy.
- Nie ma wyświetlania transkrypcji na żywo podczas mówienia (użytkownik zacznie czytać i monitorować).
- Nie ma oceny "poprawności" jako głównego wyniku.
- Nie ma nauki słownictwa, fiszek, list, gramatyki.
- Aplikacja nie jest chatbotem. LLM jest komponentem, nie interfejsem.
  - Jedyny wyjątek: moduł „Rozmowa" (GPT-Live) - głosowa rozmowa jako warunek
    pomiarowy (swobodne tury, nieprzewidywalne pytania). Obowiązują te same
    reguły: bez transkryptu na żywo, bez korekt w trakcie, metryki liczone
    z własnego nagrania (whisper-1), wyniki dopiero po rozmowie, osobno od
    statystyk sond transferowych.

---

## 2. Zasady projektowe

1. **Presja czasu jest funkcją, nie efektem ubocznym.** Timer jest widoczny i nieusuwalny.
2. **Feedback zawsze po fakcie, nigdy w trakcie.** W trakcie mówienia widoczne są maksymalnie: timer i wskaźnik "mówisz / cisza".
3. **Metryki czasowe mają pierwszeństwo przed językowymi.** Jeśli oba wskazania są sprzeczne, wygrywa czas.
4. **Błąd gramatyczny przy płynnej wypowiedzi to sukces, nie porażka.** System jawnie to komunikuje.
5. **Sesja 10-15 minut.** Trening automatyzacji jest wyczerpujący; dłuższe sesje degradują wyniki.
6. **Interfejs bez emoji.** Minimalny, wysoki kontrast, duży timer.

---

## 3. Architektura

```
apps/
  web/                      React + Vite + TypeScript + Tailwind
    src/
      audio/                AudioWorklet, recorder, VAD (onnxruntime-web)
      drills/               komponenty ekranów drilli (generyczne)
      charts/               wizualizacja postępu (recharts)
      api/                  klient HTTP
  api/                      FastAPI
    app/
      routers/              sessions, attempts, tasks, stats
      services/
        transcription.py    Whisper API
        vad.py              silero-vad na CPU (torch hub / onnx)
        metrics.py          silnik metryk - rdzeń systemu
        llm.py              Anthropic API - generowanie i ocena jakościowa
        adaptation.py       dobór poziomu trudności
      models/               SQLAlchemy
      drills/               konfiguracje drilli (ładowane z JSON)
data/
  seed_tasks.json           bank zadań startowych
  app.db                    SQLite
```

Uzasadnienie SQLite: aplikacja jednoużytkownikowa, lokalna, dane audio zostają na dysku. Migracja do Postgres tylko jeśli pojawi się multi-user.

---

## 4. Pipeline audio - najważniejsza część systemu

### 4.1 Nagrywanie (przeglądarka)

- `getUserMedia` z `echoCancellation: false`, `noiseSuppression: false`, `autoGainControl: false`.
  Uzasadnienie: przetwarzanie sygnału przez przeglądarkę zniekształca energię sygnału i psuje detekcję pauz. To jest wymóg twardy.
- `AudioWorkletNode` zbiera surowy Float32, downsampling do 16 kHz mono.
- Bufor trzymany w pamięci jako Float32Array, po zakończeniu enkodowany do WAV PCM 16-bit i wysyłany do backendu.
- Znacznik `t0` (moment pojawienia się bodźca) rejestrowany przez `performance.now()` **i** zapisywany jako offset próbki w buforze audio. Nie polegać na zegarze systemowym ani na czasie żądania HTTP.

### 4.2 VAD w przeglądarce (tylko UI na żywo)

- Silero VAD przez `onnxruntime-web`, okno 512 próbek przy 16 kHz (~32 ms).
- Służy wyłącznie do wskaźnika "mówisz / cisza" i do wykrycia końca wypowiedzi (auto-stop po 2.5 s ciszy, konfigurowalne per drill).
- Wyniki z przeglądarki **nie są** źródłem metryk.

### 4.3 VAD na serwerze (źródło prawdy)

- Ten sam model Silero VAD, uruchamiany na CPU (model ma ~1.8 MB, działa wielokrotnie szybciej niż real-time - GPU zbędne).
- Parametry: `threshold=0.5`, `min_speech_duration_ms=100`, `min_silence_duration_ms=200`, `speech_pad_ms=0`.
- Wyjście: lista segmentów mowy `[(start_s, end_s), ...]`. Z tego liczone są wszystkie metryki czasowe.
- **Kalibracja obowiązkowa:** przy pierwszym uruchomieniu użytkownik nagrywa 10 s ciszy w swoim pomieszczeniu. Mierzony jest poziom szumu tła i próg VAD jest korygowany. Bez tego pauzy będą mierzone błędnie w głośnym otoczeniu.

### 4.4 Transkrypcja (Whisper API)

- Model: `whisper-1`. Decyzja świadoma i nie do zmiany bez ponownej analizy - uzasadnienie w 4.4.1.
- `response_format: "verbose_json"`, `timestamp_granularities: ["word", "segment"]`, `language: "en"`, `temperature: 0`.
- **Krytyczne - zachowanie dysfluencji.** Whisper domyślnie usuwa "um", "uh", jąkanie, powtórzenia i fałszywe starty, ponieważ był trenowany na oczyszczonych napisach. To wycina dokładnie ten sygnał, który mierzymy. Obejście:
  - parametr `prompt` (max 224 tokeny) wypełniony przykładem mowy z dysfluencjami, np.:
    `"Um, so I was, uh, I was thinking that maybe we could, you know, we could try... I mean, it's, it's not really, hmm, how do you say it, it's not really that simple, right?"`
  - `temperature: 0`,
  - transkrypcja pojedynczej próby jako jeden plik, bez dzielenia na fragmenty.
- Timestampy słów z Whispera służą do metryk językowych i do sanity-check. **Pauzy liczone są z VAD, nie z odstępów między timestampami słów** - Whisper zaokrągla granice i przy dłuższej ciszy potrafi je przesunąć.

### 4.4.1 Dlaczego nie nowsze modele OpenAI

W lipcu 2026 OpenAI wypuściło `gpt-transcribe` (pliki, batch) i `gpt-live-transcribe` (strumień na żywo) i to one są rekomendowanym domyślnym wyborem dla nowych projektów. Dla tej aplikacji zostajemy przy `whisper-1` z dwóch powodów.

1. **Brak timestampów słów.** Żaden z nowych modeli ich nie zwraca. `whisper-1` jest jedynym modelem hostowanym przez OpenAI, który udostępnia `timestamp_granularities`. Alternatywą byłby lokalny forced alignment (CTC, działa na CPU), ale to dodatkowy komponent i dodatkowe źródło błędu - nieuzasadnione, dopóki whisper-1 jest dostępny.
2. **Normalizacja wypowiedzi.** Modele oparte na LLM czyszczą mowę agresywniej niż Whisper: usuwają wypełniacze, fałszywe starty i powtórzenia. To jest ich zaleta w typowych zastosowaniach i wada krytyczna tutaj. Nasze wymaganie jest odwrotnie skorelowane ze standardową miarą jakości transkrypcji - niższy WER na benchmarku nie oznacza lepszych danych dla tego systemu.

Różnica kosztu jest nieistotna przy tej skali: 0,006 vs 0,0045 USD za minutę, czyli poniżej 10 centów za sesję.

**Warunek ponownego rozpatrzenia:** jeśli `whisper-1` zostanie wycofany albo pojawi się model z timestampami słów i trybem dosłownym, przejście wymaga przejścia testu z sekcji 13.1 przed jakąkolwiek zmianą w produkcji.

### 4.5 Budżet czasowy

Nagranie 15 s → upload + Whisper API ≈ 1.5-3 s → VAD i metryki ≈ 0.3 s. Feedback pojawia się po ~3 s od końca wypowiedzi. To akceptowalne, bo cały feedback jest z definicji post-hoc. Wskaźnik "mówisz / cisza" na żywo pochodzi z VAD w przeglądarce i ma opóźnienie ~32 ms.

---

## 5. Metryki - definicje formalne

Wszystkie metryki liczone per próba (`attempt`), agregowane per sesja i per moduł. Oznaczenia: `T` = całkowity czas nagrania od `t0`, `P` = suma długości segmentów mowy (phonation time), `W` = liczba słów, `S` = liczba sylab (szacowana słownikiem CMUdict z fallbackiem heurystycznym).

### 5.1 Metryki czasowe (rdzeń)

| Metryka | Definicja | Jednostka | Kierunek |
|---|---|---|---|
| `ttfw` - time to first word | `start` pierwszego segmentu mowy minus `t0` | s | maleje |
| `phonation_time_ratio` | `P / T` | 0-1 | rośnie |
| `speech_rate` | `W / T * 60` | słowa/min | rośnie |
| `articulation_rate` | `W / P * 60` | słowa/min | stabilne |
| `mean_length_of_run` | średnia liczba słów między pauzami >= 250 ms | słowa | rośnie |
| `silent_pause_count` | liczba przerw >= 250 ms wewnątrz wypowiedzi | szt. | maleje |
| `long_pause_count` | liczba przerw >= 1000 ms | szt. | maleje |
| `mean_pause_duration` | średnia długość przerwy >= 250 ms | s | maleje |
| `pause_position_ratio` | udział pauz wewnątrz frazy (mid-clause) w całości pauz | 0-1 | maleje |

Uwaga do `pause_position_ratio`: pauzy na granicach zdań są naturalne i występują też u native speakerów. Pauzy w środku frazy sygnalizują problem z wydobyciem. To najlepszy pojedynczy wskaźnik automatyzacji. Klasyfikacja pozycji pauzy: pauza jest mid-clause, jeśli nie występuje bezpośrednio po znaku interpunkcyjnym w transkrypcji ani przed spójnikiem rozpoczynającym nowe zdanie.

Progi 250 ms i 1000 ms pochodzą ze standardu badań nad płynnością L2. Trzymać je jako stałe konfiguracyjne, nie zmieniać bez powodu.

### 5.2 Metryki językowe (z transkrypcji)

| Metryka | Definicja |
|---|---|
| `filler_rate` | liczba wypełniaczy (`um, uh, er, like, you know, I mean, kind of, sort of, well, actually` - lista konfigurowalna) na 100 słów |
| `repair_count` | liczba autokorekt: powtórzenie tego samego słowa/frazy, fałszywy start, zmiana kierunku wypowiedzi |
| `repetition_count` | bezpośrednie powtórzenia słowa lub frazy |
| `mtld` | Measure of Textual Lexical Diversity - odporny na długość tekstu, lepszy niż TTR przy krótkich próbkach |
| `mean_length_utterance` | średnia liczba słów w zdaniu |
| `subordination_index` | liczba zdań podrzędnych na zdanie główne (spaCy, `en_core_web_sm`) |
| `word_frequency_profile` | udział słów spoza 2000 najczęstszych (lista frekwencyjna offline) |

Detekcja autokorekt - reguły, w tej kolejności:
1. Powtórzenie n-gramu (n=1..4) w odległości <= 5 słów.
2. Fałszywy start: fragment przerwany pauzą >= 300 ms i rozpoczęty ponownie innym słowem funkcyjnym.
3. Marker naprawy: `I mean`, `sorry`, `no wait`, `or rather`, `actually no`.

### 5.3 Wskaźniki złożone

- `automaticity_index` = `z(-ttfw) + z(mean_length_of_run) + z(-mid_clause_pause_rate)`, gdzie `z` to standaryzacja wobec własnej historii użytkownika (minimum 20 prób w danym module, wcześniej pokazywane jako "kalibracja").
- `complexity_fluency_tradeoff` = `subordination_index / mean_length_of_run`. Wysoka wartość = użytkownik buduje struktury, których nie utrzymuje. To bezpośredni pomiar objawu "nadmiernie komplikuję to, co chcę powiedzieć". System ma jawny cel: **obniżyć ten wskaźnik**, nawet kosztem prostszych zdań.
- `cognitive_load_curve` = `ttfw` i `filler_rate` w funkcji numeru próby w sesji. Wzrost w drugiej połowie sesji = zmęczenie. Po przekroczeniu progu (wzrost `ttfw` o 40% względem pierwszych 5 prób) aplikacja **kończy sesję** i mówi o tym wprost.

### 5.4 Metryki struktur gramatycznych

Liczone tylko dla prób, które mają przypisane `target_structure` (patrz sekcja 7.2). spaCy `en_core_web_sm` plus reguły na tagach morfologicznych i drzewie zależności.

| Metryka | Definicja |
|---|---|
| `structure_used` | czy docelowa konstrukcja pojawiła się w wypowiedzi (bool) |
| `structure_count` | ile razy |
| `avoidance` | `structure_used == false` przy zadaniu, które konstrukcji wymaga - metryka wiodąca |
| `ttfw_structured` | `ttfw` dla prób z daną strukturą, porównywane z `ttfw` bazowym użytkownika |
| `pre_structure_pause` | najdłuższa pauza w oknie 3 słów poprzedzających konstrukcję |
| `structure_accuracy` | poprawność formy (np. `would have + past participle`), zbierana, ale **nie pokazywana po próbie** |

`avoidance` jest tu ważniejsze niż poprawność. Osoba z C1 w rozumieniu omija trudne konstrukcje odruchowo i nie zdaje sobie z tego sprawy - zamiast trzeciego okresu warunkowego mówi dwa proste zdania w czasie przeszłym. Wypowiedź jest poprawna, komunikat przechodzi, a konstrukcja pozostaje nieaktywna latami. To jest dokładnie ten mechanizm, który system ma ujawnić.

`pre_structure_pause` mierzy koszt planowania. Jeśli przed każdym `would have` pojawia się 800 ms ciszy, konstrukcja jest znana, ale nie zautomatyzowana - i to jest inna diagnoza niż jej nieznajomość.

### 5.5 Czego NIE mierzymy jako wyniku

Poprawności gramatycznej, akcentu, wymowy, "poziomu CEFR". Błędy gramatyczne są zbierane w tle wyłącznie do jednego celu: wykrycia 3-5 wzorców powtarzalnych i wyświetlenia ich **raz w tygodniu**, poza sesją treningową, jako lista obserwacji. Nigdy w trakcie ani bezpośrednio po próbie.

---

## 6. Model danych

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  created_at TEXT,
  noise_floor_db REAL,          -- z kalibracji
  vad_threshold REAL DEFAULT 0.5
);

CREATE TABLE tasks (
  id TEXT PRIMARY KEY,          -- np. "rr_0042"
  module TEXT NOT NULL,         -- rapid_response, paraphrase, ...
  difficulty INTEGER NOT NULL,  -- 1-10
  target_structure TEXT,        -- NULL = zadanie bez wymuszonej struktury
  structure_mode TEXT,          -- 'explicit' | 'implicit' | NULL
  prompt_text TEXT NOT NULL,
  payload JSON,                 -- pola specyficzne dla modułu (np. forbidden_words)
  tags JSON,
  source TEXT                   -- 'seed' | 'llm'
);

CREATE TABLE sessions (
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  module TEXT,
  started_at TEXT,
  ended_at TEXT,
  ended_reason TEXT,            -- 'completed' | 'fatigue' | 'aborted'
  target_difficulty INTEGER
);

CREATE TABLE attempts (
  id INTEGER PRIMARY KEY,
  session_id INTEGER,
  task_id TEXT,
  attempt_index INTEGER,        -- numer w sesji, do krzywej zmęczenia
  round_index INTEGER DEFAULT 1,-- dla Story Loop / Paraphrase
  t0_iso TEXT,
  audio_path TEXT,
  duration_s REAL,
  transcript TEXT,
  words JSON,                   -- [{word, start, end}]
  vad_segments JSON,            -- [[start, end], ...]
  metrics JSON,                 -- wszystkie metryki z sekcji 5
  llm_eval JSON,                -- ocena jakościowa, patrz sekcja 8
  created_at TEXT
);

CREATE TABLE progress_snapshots (
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  module TEXT,
  date TEXT,
  rolling_metrics JSON          -- średnie kroczące z 7 i 30 dni
);
```

Audio przechowywane na dysku w `data/audio/{session_id}/{attempt_id}.wav`. Retencja: 30 dni, potem kasowane, metryki zostają. Konfigurowalne.

---

## 7. Silnik drilli - wspólny kontrakt

Wszystkie 10 modułów to jedna maszyna stanów z inną konfiguracją. Nie implementować ich osobno.

```
IDLE -> PRESENT (bodziec) -> [PREP?] -> RECORD -> PROCESS -> FEEDBACK -> (next | END)
```

Konfiguracja drilla (JSON, ładowana z `app/drills/*.json`):

```json
{
  "id": "rapid_response",
  "name": "Rapid Response",
  "stimulus": "text | audio | text+audio",
  "prep_time_s": 0,
  "min_speak_s": 5,
  "max_speak_s": 15,
  "auto_stop_silence_s": 2.5,
  "rounds": 1,
  "attempts_per_session": 12,
  "primary_metrics": ["ttfw", "mean_length_of_run"],
  "target": {"ttfw": {"max": 1.5}},
  "llm_eval": false,
  "show_timer": true,
  "show_transcript_during": false
}
```

### 7.1 Konfiguracje modułów

| Moduł | prep | czas mówienia | rundy | metryki wiodące | ocena LLM |
|---|---|---|---|---|---|
| **Rapid Response** | 0 s | 5-15 s | 1 | `ttfw`, `long_pause_count` | nie |
| **Paraphrase** | 0 s | 3x po 15 s | 3 | dystans leksykalny między rundami, `ttfw` rundy 2 i 3 | tak |
| **Simplify** | 5 s | 20 s | 1 | `subordination_index` (ma spaść), `word_frequency_profile` | tak |
| **Story Loop** | 0 s | 90/60/45 s | 3 | `mean_length_of_run` rosnące, `filler_rate` malejący | nie |
| **Describe Without the Word** | 0 s | 30 s | 1 | `ttfw`, `mid_clause_pause_rate`, użycie słowa zakazanego = fail | tak (weryfikacja trafności) |
| **Unexpected Questions** | 0 s | 15 s | 1 | `ttfw` (adaptacja trudności) | nie |
| **Shadow Conversation** | 0 s | 8 s | 8-12 wymian | `ttfw` per wymiana, spójność | nie |
| **Idea Expansion** | 0 s | 45 s | 1 | `mean_length_utterance`, liczba zdań (cel: 5) | tak |
| **Fluency Sprint** | 0 s | 120 s | 1 | `phonation_time_ratio`, `long_pause_count` | nie |
| **Conversation Simulation** | 0 s | zmienny | dialog | `ttfw` per tura, `cognitive_load_curve` | tak |

Uwagi implementacyjne do wybranych modułów:

- **Story Loop**: ta sama historia trzy razy, z malejącym limitem czasu. Zasada 4/3/2 z metodyki nauczania. Cel: przy rundzie 3 `mean_length_of_run` ma być wyższy niż w rundzie 1. Wynik pokazywany jako różnica między rundami, nie jako wartość bezwzględna.
- **Paraphrase**: dystans leksykalny liczony jako `1 - (|A ∩ B| / |A ∪ B|)` na lemmach treściowych, z pominięciem słów funkcyjnych. Trzy wersje muszą mieć parami dystans > 0.5, inaczej runda nie zalicza się.
- **Describe Without the Word**: lista `forbidden_words` obejmuje słowo docelowe, jego formy fleksyjne i podane synonimy. Sprawdzenie po transkrypcji, na lemmach.
- **Shadow Conversation**: zdania AI odtwarzane przez TTS (Web Speech Synthesis wystarcza, głos `en-US`). Nagrywanie startuje automatycznie w momencie zakończenia odtwarzania - to jest `t0`.
- **Fluency Sprint**: pojedyncza prosta karta tematyczna, 120 s. Jedyna zasada: nie przestawać. Feedback pokazuje wykres phonation w czasie - użytkownik widzi, gdzie się zaciął.

### 7.2 Wymiar struktur gramatycznych

Struktura gramatyczna jest **prostopadłym wymiarem zadania, nie osobnym modułem**. Nie implementować drilla "conditionals". Zamiast tego zadanie ma pole `target_structure`, a użytkownik może uruchomić dowolny moduł z filtrem na strukturę: Rapid Response tylko z trzecim okresem warunkowym, Fluency Sprint tylko o przyszłości, Describe Without the Word z wymuszoną stroną bierną.

**Zasada projektowania promptu:** struktura ma być nieunikniona, nie zalecana. Prompt "Use the third conditional to talk about a mistake" jest zły - to ćwiczenie gramatyczne. Prompt "What is the one decision that would have completely changed your career?" jest dobry - odpowiedź bez trzeciego okresu warunkowego wymaga świadomego obejścia, a to obejście jest właśnie tym, co mierzymy.

#### Dwa tryby

- `structure_mode: "explicit"` - nazwa struktury i przykład są widoczne przed startem. Buduje automatyzację przez powtórzenie w warunkach presji czasu. Używany na początku pracy z daną strukturą.
- `structure_mode: "implicit"` - prompt wymusza strukturę, ale użytkownik nie wie, o co chodzi. Mierzy, czy struktura jest dostępna spontanicznie.

Ten sam prompt obsługuje oba tryby - `structure_mode` jest wybierane przy budowaniu sesji, nie jest cechą zadania. Treść podpowiedzi (nazwa struktury i jedno zdanie przykładowe) pochodzi z listy `structures` w `seed_tasks.json`, nie z samego zadania. Dlatego kolumna `structure_mode` w tabeli `tasks` może być `NULL`; wartość rozstrzygająca trafia do `attempts.metrics`.

**Różnica `avoidance` między trybem jawnym a ukrytym dla tej samej struktury jest głównym wynikiem tego podsystemu.** Niska w jawnym, wysoka w ukrytym oznacza: znasz konstrukcję, ale nie sięgasz po nią sam. To inna sytuacja niż wysoka w obu, i wymaga innego treningu. System dobiera proporcję trybów automatycznie: dopóki `avoidance` w trybie jawnym > 0.2, zadania są w 80% jawne; poniżej tego progu proporcja odwraca się na 30/70 na rzecz ukrytych.

#### Detekcja

spaCy, reguły na `tag_`, `morph` i drzewie zależności. Dla każdej struktury para: wzorzec pozytywny i lista typowych obejść. Przykład dla trzeciego okresu warunkowego:

```python
# pozytywny: "if" + had + VBN  ...  would/could/might + have + VBN
# obejście:  zdanie o przeszłości bez modalu perfektywnego,
#            czyli treść kontrfaktyczna wyrażona dwoma zdaniami w Past Simple
```

Detekcja obejść jest z natury niepewna. Dlatego `avoidance` = brak wzorca pozytywnego w zadaniu oznaczonym jako wymagające struktury. Prostsze i wystarczające. Trafność promptów weryfikowana jednorazowo: native lub LLM odpowiada na 10 promptów każdej struktury; jeśli w więcej niż 2 na 10 odpowiedziach konstrukcja się nie pojawia naturalnie, prompt jest zły i wraca do poprawki.

#### Lista struktur (`target_structure`)

```
future_will, future_going_to, future_continuous, future_perfect,
past_simple, past_continuous, past_perfect, used_to, would_habitual,
conditional_0, conditional_1, conditional_2, conditional_3, conditional_mixed,
modal_speculation_present, modal_speculation_past,
passive_voice, reported_speech, relative_clauses,
gerund_vs_infinitive, wish_if_only
```

#### Prezentacja wyników

Mapa cieplna: struktury w wierszach, kolumny to `avoidance`, `ttfw_structured` względem bazowego i `pre_structure_pause`. Dostępna wyłącznie na ekranie postępu, nigdy w trakcie sesji ani w feedbacku po próbie. Zero korekty formy - jeśli powiedziałeś "if I would have known", system to zapisuje i nie mówi nic. Trafi to co najwyżej do obserwacji tygodniowych.

---

## 8. Rola LLM (Anthropic API)

LLM robi trzy rzeczy i nic więcej:

1. **Generuje zadania** offline, do bazy, poza sesją. Nie w trakcie treningu - latencja jest niedopuszczalna. Nocny/na żądanie job dogenerowuje zadania do poziomów trudności, w których zapas spadł poniżej 20 sztuk.
2. **Ocena jakościowa** wybranych modułów (kolumna `llm_eval` w tabeli powyżej): czy parafraza faktycznie znaczy to samo, czy uproszczenie zachowało sens, czy opis pozwala odgadnąć pojęcie. Wywoływane **po** zakończeniu próby, asynchronicznie.
3. **Prowadzi dialog** w Conversation Simulation i generuje pytania w Unexpected Questions.

LLM **nie** ocenia płynności. Płynność jest mierzona, nie oceniana.

Konfiguracja: `ANTHROPIC_API_KEY` i `ANTHROPIC_MODEL` z `.env`. Nazwę modelu ustawić jako zmienną środowiskową i zweryfikować aktualną listę w https://docs.claude.com/en/docs/about-claude/models - nie hardkodować w kodzie.

Prompty trzymane w `app/prompts/*.md`, nie w kodzie Pythona.

Wymóg formatu: każdy prompt oceniający zwraca wyłącznie JSON, bez markdown, według schematu walidowanego Pydantic. Przy błędzie parsowania - jeden retry, potem `llm_eval: null` i próba zostaje bez oceny jakościowej. Brak oceny LLM nigdy nie blokuje zapisania metryk.

---

## 9. Adaptacja trudności

Algorytm celowo prosty i przewidywalny.

```
strefa_docelowa = ttfw w przedziale [0.8 s, 2.0 s]

po każdych 5 próbach w module:
  m = mediana ttfw z ostatnich 5 prób
  jeśli m < 0.8 i brak fail (np. użycie słowa zakazanego):  difficulty += 1
  jeśli m > 3.0 lub >= 2 fail:                              difficulty -= 1
  w przeciwnym razie:                                        bez zmian
difficulty ograniczone do [1, 10]
```

Trudność zadania jest cechą treści (abstrakcyjność pojęcia, obcość tematu, wymagana precyzja), nie długości czasu. Limity czasowe są stałe per moduł - to one tworzą presję i nie wolno ich rozluźniać, gdy jest trudno.

---

## 10. API

```
POST   /api/sessions                    -> {session_id, module, first_task}
GET    /api/sessions/{id}/next-task     -> {task, drill_config}
POST   /api/attempts                    multipart: audio(wav) + json(session_id, task_id, t0_offset_samples, attempt_index, round_index)
                                        -> 202 {attempt_id}   (przetwarzanie w tle)
GET    /api/attempts/{id}               -> {metrics, transcript, llm_eval, status}
POST   /api/sessions/{id}/end           -> {summary, fatigue_detected}
GET    /api/stats/progress?module=&days= -> szeregi czasowe metryk
GET    /api/stats/structures            -> mapa cieplna: avoidance, ttfw_structured, pre_structure_pause per struktura
POST   /api/calibrate                   multipart: audio(10 s ciszy) -> {noise_floor_db, vad_threshold}
POST   /api/tasks/generate              body: {module, difficulty, count} -> generowanie przez LLM
```

Przetwarzanie próby: FastAPI `BackgroundTasks` wystarczy przy jednym użytkowniku. Frontend odpytuje `GET /api/attempts/{id}` co 500 ms do `status: "done"`.

---

## 11. Frontend - ekrany

1. **Start**: wybór modułu, informacja o aktualnym poziomie, przycisk startu. Opcjonalny filtr struktury gramatycznej - domyślnie wyłączony, sesja miesza wtedy zadania z `target_structure` i bez. Bez tekstu motywacyjnego.
2. **Kalibracja** (jednorazowo): 10 s ciszy.
3. **Drill**: bodziec (duża czcionka, wyśrodkowany), timer odliczający, wskaźnik mowa/cisza jako pasek. Nic więcej. Tło zmienia odcień, gdy zostaje 20% czasu.
4. **Feedback po próbie** (3-4 s ekspozycji, potem automatyczne przejście dalej): trzy liczby - czas startu, najdłuższy nieprzerwany odcinek, liczba długich pauz. Transkrypcja dostępna pod rozwinięciem, domyślnie zwinięta.
5. **Podsumowanie sesji**: wykres krzywej zmęczenia, porównanie z medianą z ostatnich 7 dni, jedno zdanie interpretacji.
6. **Postęp**: szeregi czasowe `ttfw`, `mean_length_of_run`, `complexity_fluency_tradeoff` (recharts).
7. **Struktury**: mapa cieplna z sekcji 7.2 plus zestawienie `avoidance` w trybie jawnym vs ukrytym. Wejście tylko z menu, nigdy automatycznie po sesji.
8. **Obserwacje tygodniowe**: powtarzalne wzorce błędów, generowane raz w tygodniu.

Zasada UI: podczas stanu RECORD na ekranie nie może pojawić się żaden tekst w języku angielskim poza bodźcem. Żadnych podpowiedzi, żadnego autouzupełniania, żadnej transkrypcji.

---

## 12. Zakres MVP i kolejność

**Faza 1 - fundament (bez tego reszta nie ma sensu)**
1. Pipeline audio: AudioWorklet, WAV 16 kHz, poprawny `t0`.
2. Kalibracja szumu tła.
3. VAD serwerowy + `metrics.py` z sekcji 5.1.
4. Whisper API z zachowaniem dysfluencji + test regresyjny (sekcja 13).
5. Silnik drilli jako maszyna stanów + jedna konfiguracja.

**Faza 2 - trzy moduły w pełni**
6. Rapid Response, Describe Without the Word, Fluency Sprint.
7. Ekran feedbacku i podsumowania sesji.
8. Adaptacja trudności.

**Faza 3**
9. Metryki językowe (5.2), wskaźniki złożone (5.3), ekran postępu.
10. Podsystem struktur gramatycznych (7.2): detekcja spaCy, filtr na ekranie startu, mapa cieplna.
11. Pozostałe siedem modułów jako konfiguracje.
12. Integracja LLM: generowanie zadań i ocena jakościowa.

Moduł Conversation Simulation ostatni - wymaga TTS, zarządzania turami i jest najmniej wartościowy na starcie.

---

## 13. Testy krytyczne

Te cztery testy muszą istnieć, reszta według uznania.

1. **Test zachowania dysfluencji.** Plik audio z nagraną wypowiedzią zawierającą minimum 5 wypełniaczy i 2 powtórzenia. Test przechodzi, gdy transkrypcja zawiera >= 80% z nich. Jeśli konfiguracja Whispera zostanie kiedykolwiek zmieniona i test padnie, cały system metryk językowych jest bezwartościowy.
2. **Test dokładności `ttfw`.** Syntetyczny plik: 2.0 s ciszy, potem mowa. Zmierzone `ttfw` musi mieścić się w 2.0 s +/- 100 ms. Analogicznie test wykrywania pauz o znanej długości (0.3 s, 0.5 s, 1.5 s).
3. **Test kalibracji VAD.** Ten sam plik mowy zmiksowany z szumem tła na trzech poziomach. Liczba wykrytych pauz nie może różnić się o więcej niż 1 między wariantami po kalibracji.
4. **Test detekcji struktur.** Dla każdej pozycji z listy `target_structure` zestaw 5 zdań pozytywnych i 5 negatywnych (w tym typowe obejścia). Wymagana precyzja i czułość >= 0.9. Fałszywie dodatnia detekcja zaniża `avoidance` i unieważnia cały podsystem, więc ten test blokuje wdrożenie mapy cieplnej.

---

## 14. Ryzyka i decyzje do podjęcia w trakcie

- **Whisper zbyt dobrze poprawia mowę.** Jeśli mimo `prompt` z dysfluencjami transkrypcja pozostaje wygładzona, metryki językowe tracą wiarygodność. Metryki czasowe pozostają nienaruszone, bo pochodzą z VAD - system nadal działa. Plan awaryjny: `filler_rate` i `repair_count` oznaczone jako niepewne i wyłączone z `automaticity_index`.
- **Efekt sufitu na `ttfw`.** Po kilku tygodniach czas startu spadnie do ~0.5 s i przestanie różnicować. Wtedy metryką wiodącą staje się `mean_length_of_run` i `mid_clause_pause_rate`. Przewidzieć to w interfejsie postępu.
- **Wyuczenie się banku zadań.** Przy 12 próbach dziennie bank 500 zadań wyczerpuje się w ~6 tygodni. Stąd generator LLM jest częścią systemu, nie dodatkiem.
- **Mikrofon.** Metryki nie są porównywalne między różnymi mikrofonami i pomieszczeniami. Zapisywać `deviceId` i ostrzegać przy zmianie sprzętu, że szereg czasowy ma nieciągłość.
