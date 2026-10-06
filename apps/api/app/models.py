from datetime import datetime, timezone

from sqlalchemy import Boolean, JSON, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    noise_floor_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    vad_threshold: Mapped[float] = mapped_column(Float, default=0.5)


class AppSetting(Base):
    """Ustawienia instancji zapisane przez użytkownika (klucz API, hasło).

    Wartości stąd mają pierwszeństwo przed zmiennymi środowiskowymi, dzięki
    czemu zmiana w interfejsie nie wymaga restartu ani redeployu.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, default=now_iso)


class ReadingAttempt(Base):
    """Trener tempa czytania - świadomie OSOBNO od Attempt.

    Czytanie na głos nie ma komponentu wydobywania z pamięci, więc jego metryki
    nie mogą trafiać do statystyk mowy spontanicznej. Osobna tabela gwarantuje,
    że nigdy się nie zmieszają.
    """

    __tablename__ = "reading_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    target_wpm: Mapped[int] = mapped_column(Integer, default=130)
    reference_text: Mapped[str] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    words: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="processing")


# --- profil użytkownika i słownictwo (spec §6) ------------------------------


class PersonalContext(Base):
    """Profil budowany poza sesją: praca, projekty, zainteresowania, sytuacje.

    Wersjonowany - edycja tworzy nowy wiersz zamiast nadpisywać poprzedni,
    żeby dało się prześledzić, jak zmieniał się kontekst treści.
    """

    __tablename__ = "personal_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class KnownVocabulary(Base):
    """Lemmy znanego słownictwa - walidacja seed_text (spec §3 zasada 3)."""

    __tablename__ = "known_vocabulary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lemma: Mapped[str] = mapped_column(Text, unique=True, index=True)
    source: Mapped[str] = mapped_column(Text)  # 'top3000' | 'import'
    added_at: Mapped[str] = mapped_column(Text, default=now_iso)


# --- domeny i materiał sesji (spec §6, §7) ----------------------------------


class Domain(Base):
    """Obszar tematyczny, trwa 5-7 sesji zanim generator przejdzie do kolejnego."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")  # active | done
    target_sessions: Mapped[int] = mapped_column(Integer, default=5)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[str] = mapped_column(Text, default=now_iso)


class SourcePack(Base):
    """Materiał na jedną sesję, generowany z wyprzedzeniem (spec §7)."""

    __tablename__ = "source_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(Integer, ForeignKey("domains.id"))
    seed_text: Mapped[str] = mapped_column(Text)
    guiding_questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    transfer_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="draft")  # draft|validated|rejected
    validation_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


# --- chunki: bank domenowy (A) i funkcyjny (B) - spec dodatek v2 -----------


class Chunk(Base):
    """Fraza wielowyrazowa. bank='domain' rotuje z SourcePack, bank='function'
    jest stały (~20 fraz, generowany raz skryptem seed), ćwiczony masowo."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank: Mapped[str] = mapped_column(Text)  # 'domain' | 'function'
    text: Mapped[str] = mapped_column(Text)
    # opis sytuacji po polsku do Trybu A (dostęp) - "na ekranie polski opis
    # sytuacji, użytkownik mówi sam chunk" (dodatek v2)
    prompt_pl: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_pack_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("source_packs.id"), nullable=True
    )
    # harmonogram SM-2 - używany głównie dla bank='function'
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_sessions: Mapped[int] = mapped_column(Integer, default=1)
    next_due_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_fast_exposures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class ChunkExposure(Base):
    """Log pojedynczej ekspozycji na chunk (Tryb A - dostęp, Tryb B - wszycie)."""

    __tablename__ = "chunk_exposures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[int] = mapped_column(Integer, ForeignKey("chunks.id"))
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("speaking_sessions.id"))
    mode: Mapped[str] = mapped_column(Text)  # 'access' | 'embed'
    rt_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    silence_exceeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


# --- sesja, rundy, próby, metryki (spec §3, §6) -----------------------------


class SpeakingSession(Base):
    """Sesja = jeden blok: jeden SourcePack, powtarzany 4 razy (spec §3 zasada 1).

    Nazwana SpeakingSession (nie Session) żeby nie kolidować z
    sqlalchemy.orm.Session, powszechnie importowaną jako `Session` w routerach.
    """

    __tablename__ = "speaking_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), default=1)
    domain_id: Mapped[int] = mapped_column(Integer, ForeignKey("domains.id"))
    source_pack_id: Mapped[int] = mapped_column(Integer, ForeignKey("source_packs.id"))
    support_ceiling_at_start: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[str] = mapped_column(Text, default=now_iso)
    ended_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    interrupted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    phases_completed: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # sonda "far" (spec zmian §6) generowana raz przy starcie, poza aktywną
    # domeną - najlepszy wysiłek: None jeśli LLM zawiódł/wyłączony, wtedy
    # frontend pomija ten krok zamiast blokować sesję
    far_transfer_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # kolejność ["near","far"] wylosowana raz przy starcie (spec zmian §6.3 -
    # nie zawsze near przed far), trzymana żeby resume dawał ten sam porządek
    transfer_order: Mapped[list | None] = mapped_column(JSON, nullable=True)


class Round(Base):
    """Jeden z 4 przebiegów fazy głównej (spec §3, §4)."""

    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("speaking_sessions.id"))
    number: Mapped[int] = mapped_column(Integer)  # 1-4
    support_level: Mapped[int] = mapped_column(Integer)  # 0-4
    prep_s: Mapped[int] = mapped_column(Integer)
    speak_limit_s: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    ended_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class TransferProbe(Base):
    """Faza 4: jedyny prawdziwy pomiar, jedyne źródło wykresu postępu (spec §3).

    Rozdzielona na Near/Far (spec zmian §6): jedna sesja ma teraz do dwóch
    wierszy, po jednym na `probe_type`, stąd unikalność złożona zamiast
    unikalności samego session_id. Wiersze sprzed tej zmiany mają
    probe_type='legacy' (migracja, zobacz app/migrations.py).
    """

    __tablename__ = "transfer_probes"
    __table_args__ = (UniqueConstraint("session_id", "probe_type", name="ux_transfer_probes_session_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("speaking_sessions.id"))
    attempt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("attempts.id"), nullable=True
    )
    # 'near' | 'far' | 'legacy' (wiersze sprzed rozdziału near/far)
    probe_type: Mapped[str] = mapped_column(Text, default="legacy")
    # treść faktycznie zadanego pytania - dla near to SourcePack.transfer_prompt,
    # dla far pytanie z generatora far_transfer (nie zależy od aktywnej domeny)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_in_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 'answered' | 'redirected' | 'stalled' - answered i redirected równoważne
    # (poprawka v2B), tylko stalled jest sygnałem negatywnym. Klasyfikacja LLM
    # post-hoc, nigdy pokazywana jako ocena.
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_classified_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Attempt(Base):
    """Jedna nagrana próba: rundy głównej, chunk drillu, sondy transferowej,
    trialu diagnostycznego, albo próby recovery drillu.

    Dokładnie jedno z round_id / chunk_exposure_id / transfer_probe_id /
    diagnostic_trial_id / recovery_attempt_id jest ustawione. Audio kasowane
    po analizie (audio_path wraca do None) - transkrypcja zostaje.
    """

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("rounds.id"), nullable=True)
    chunk_exposure_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chunk_exposures.id"), nullable=True
    )
    transfer_probe_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("transfer_probes.id"), nullable=True
    )
    # Bottleneck Diagnostic (spec zmian §2) - nowe w Etapie 2
    diagnostic_trial_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("diagnostic_trials.id"), nullable=True
    )
    # Recovery Drill (spec zmian §8) - nowe w Etapie 3
    recovery_attempt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("recovery_attempts.id"), nullable=True
    )
    t0_iso: Mapped[str | None] = mapped_column(Text, nullable=True)
    t0_offset_samples: Mapped[int] = mapped_column(Integer, default=0)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ustawiane tylko dla R1 (spec dodatek v2 - zadanie własnej transkrypcji):
    # audio zostaje żywe do tego czasu zamiast być skasowane od razu po analizie
    audio_expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    words: Mapped[list | None] = mapped_column(JSON, nullable=True)
    vad_segments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    # 'processing' | 'done' | 'error'
    status: Mapped[str] = mapped_column(Text, default="processing")


class FluencyMetrics(Base):
    """Metryki płynności per próba (spec §5). Pola nośne dla reguł wsparcia i
    baseline'u są kolumnami; reszta trafia do `extra` jako jeden blok JSON."""

    __tablename__ = "fluency_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("attempts.id"), unique=True)

    articulation_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_length_of_run: Mapped[float | None] = mapped_column(Float, nullable=True)
    phonation_time_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid_clause_pause_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid_clause_pause_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    clause_final_pause_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    clause_final_pause_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)
    # opisowe, nigdy karane ani wchodzące do reguł adaptacji (poprawka v2A)
    filled_pause_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # wyłącznie diagnostyczne poza chunk drillem trybu A (spec §5, §NOWE Faza 2)
    ttfw: Mapped[float | None] = mapped_column(Float, nullable=True)
    clause_segmentation_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Baseline(Base):
    """Mediana krocząca per metryka, okno 10 sond transferowych (spec §5).

    UWAGA (spec zmian §6.5): od rozdziału sondy na Near/Far ta tabela jest
    zamrożona - nowy kod jej nie czyta ani nie zapisuje, żeby nie zmieszać
    starego baseline'u (sprzed rozróżnienia near/far) z nowymi seriami. Została
    wyłącznie po to, żeby nie tracić historii. Zobacz TransferBaseline.
    """

    __tablename__ = "baselines"

    metric_name: Mapped[str] = mapped_column(Text, primary_key=True)
    recent_values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    median: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, default=now_iso)


class TransferBaseline(Base):
    """Mediana krocząca per (metryka, probe_type) - następca Baseline (spec
    zmian §6.5): "primary baseline: far, secondary baseline: near", nigdy
    mieszane z sobą ani ze starym Baseline."""

    __tablename__ = "transfer_baselines"
    __table_args__ = (UniqueConstraint("metric_name", "probe_type", name="ux_transfer_baselines_metric_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_name: Mapped[str] = mapped_column(Text)
    probe_type: Mapped[str] = mapped_column(Text)  # 'near' | 'far'
    recent_values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    median: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, default=now_iso)


class KeywordPlan(Base):
    """Faza planowania hasłami zamiast pełnego pisania (spec zmian §3).

    Maks. 3 krótkie hasła (walidacja w routerze), czas na zapisanie ich maleje
    wraz z poziomem wsparcia (KEYWORD_PLANNING_S). Zastępuje WritingRehearsal
    jako domyślny scaffold - WritingRehearsal zostaje jako opcjonalny rescue
    mode (spec zmian §3.2).
    """

    __tablename__ = "keyword_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("speaking_sessions.id"))
    items: Mapped[list] = mapped_column(JSON)
    planning_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class WritingRehearsal(Base):
    """Faza -1: pisanie przed mówieniem, tylko gdy support_ceiling >= 3 (dodatek v2)."""

    __tablename__ = "writing_rehearsals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("speaking_sessions.id"))
    text: Mapped[str] = mapped_column(Text)
    duration_s: Mapped[float] = mapped_column(Float)
    word_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class SelfTranscription(Base):
    """Zadanie po sesji: własna transkrypcja R1 vs Whisper (dodatek v2).

    Nie wchodzi do żadnych statystyk - czysto introspekcyjne, aplikacja nie
    komentuje różnic.
    """

    __tablename__ = "self_transcriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("attempts.id"), unique=True)
    user_text: Mapped[str] = mapped_column(Text)
    whisper_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class DiagnosticSession(Base):
    """Bottleneck Diagnostic (spec zmian §2): sesja diagnostyczna A/B/C/D
    (+ opcjonalna kontrola PL), świadomie osobna od SpeakingSession - nigdy nie
    miesza się ze zwykłymi statystykami postępu."""

    __tablename__ = "diagnostic_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="in_progress")  # in_progress | completed
    language_control_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class DiagnosticTrial(Base):
    """Jeden warunek diagnostyczny (spec zmian §2.1): cold / supplied_ideas /
    self_plan / repetition / native_control. repetition ma source_trial_id
    wskazujący self_plan (to samo pytanie, bez ponownego planowania)."""

    __tablename__ = "diagnostic_trials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagnostic_session_id: Mapped[int] = mapped_column(Integer, ForeignKey("diagnostic_sessions.id"))
    condition: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    # supplied_ideas: {"ideas": [...]}; self_plan (po zapisaniu planu): {"items": [...]}
    support_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    planning_seconds: Mapped[int] = mapped_column(Integer)
    speaking_limit_seconds: Mapped[int] = mapped_column(Integer)
    source_trial_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("diagnostic_trials.id"), nullable=True
    )
    attempt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("attempts.id"), nullable=True)
    order_in_session: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class RecoveryAttempt(Base):
    """Recovery Drill (spec zmian §8): odzyskanie kontroli nad wypowiedzią po
    zgubieniu wątku / przeformułowaniu / dopytaniu. Nigdy nie oceniane
    treściowo - tylko metryki czasowe jak każda inna Attempt."""

    __tablename__ = "recovery_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)  # lost_thread | reformulation | clarification_followup
    prompt: Mapped[str] = mapped_column(Text)
    follow_up_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("attempts.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class ConversationSession(Base):
    """Rozmowa głosowa z GPT-Live - świadomie OSOBNO od Attempt/FluencyMetrics.

    Płynność w swobodnej rozmowie (tury wywołane przez rozmówcę, back-channele)
    nie jest porównywalna z sondami transferowymi, więc jej metryki nie mogą
    trafić do statystyk postępu mowy planowanej - tak samo jak ReadingAttempt.
    """

    __tablename__ = "conversation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("domains.id"), nullable=True)
    persona: Mapped[str] = mapped_column(Text)
    target_chunks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    live_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_minutes: Mapped[int] = mapped_column(Integer, default=15)
    started_at: Mapped[str] = mapped_column(Text, default=now_iso)
    ended_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    billed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'active' | 'processing' | 'done' | 'error'
    status: Mapped[str] = mapped_column(Text, default="active")
    debrief: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ConversationTurn(Base):
    """Jedna tura użytkownika: okno od końca wypowiedzi rozmówcy do końca własnej."""

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversation_sessions.id"))
    number: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)  # koniec wypowiedzi rozmówcy (t0)
    end_s: Mapped[float] = mapped_column(Float)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SupportEvent(Base):
    """Historia zmian support_ceiling z uzasadnieniem liczbowym (spec §4, §6)."""

    __tablename__ = "support_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("speaking_sessions.id"))
    from_level: Mapped[int] = mapped_column(Integer)
    to_level: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(Text)  # 'up' | 'down'
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
