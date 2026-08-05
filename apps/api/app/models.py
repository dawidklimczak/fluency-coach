from datetime import datetime, timezone

from sqlalchemy import JSON, Float, ForeignKey, Integer, Text
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


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    module: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    target_structure: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(Text, default="seed")


class LearningSession(Base):
    """Sesja nauki: otwierana przez użytkownika, mieści dowolną liczbę
    przebiegów drilli (TrainingSession); zamykana z podsumowaniem i feedbackiem."""

    __tablename__ = "learning_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), default=1)
    started_at: Mapped[str] = mapped_column(Text, default=now_iso)
    ended_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TrainingSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    learning_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learning_sessions.id"), nullable=True
    )
    module: Mapped[str] = mapped_column(Text)
    started_at: Mapped[str] = mapped_column(Text, default=now_iso)
    ended_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_difficulty: Mapped[int] = mapped_column(Integer, default=1)
    structure_filter: Mapped[str | None] = mapped_column(Text, nullable=True)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"))
    task_id: Mapped[str] = mapped_column(Text, ForeignKey("tasks.id"))
    attempt_index: Mapped[int] = mapped_column(Integer)
    round_index: Mapped[int] = mapped_column(Integer, default=1)
    t0_iso: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    words: Mapped[list | None] = mapped_column(JSON, nullable=True)
    vad_segments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_eval: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    # 'processing' | 'done' | 'error' - potrzebne do odpytywania z frontendu
    status: Mapped[str] = mapped_column(Text, default="processing")


class ProgressSnapshot(Base):
    __tablename__ = "progress_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    module: Mapped[str] = mapped_column(Text)
    date: Mapped[str] = mapped_column(Text)
    rolling_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Observation(Base):
    """Obserwacje tygodniowe (spec 5.5): powtarzalne wzorce błędów, poza sesją."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    period_start: Mapped[str] = mapped_column(Text)
    period_end: Mapped[str] = mapped_column(Text)
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)


class ModuleState(Base):
    """Bieżący poziom trudności per moduł (jeden użytkownik)."""

    __tablename__ = "module_state"

    module: Mapped[str] = mapped_column(Text, primary_key=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[str] = mapped_column(Text, default=now_iso)
