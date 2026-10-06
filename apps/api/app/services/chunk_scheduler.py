"""Bank A/B chunków (spec dodatek v2 - Faza 2 rozbudowana).

Bank A (domenowy) rotuje z SourcePack - żadnego harmonogramu, po prostu
wszystkie chunki bieżącego packu. Bank B (funkcyjny) jest stały (~20 fraz,
seed jednorazowy, scripts/seed_function_chunks.py) i ćwiczony masowo:
harmonogram jest uproszczonym odpowiednikiem SM-2 - nie klasyczną formułą z
ease factorem (tu nie ma naturalnej oceny jakości przypomnienia jak w Anki),
tylko progiem czasu reakcji: 3 kolejne sesje z medianą RT < 500 ms podwajają
interwał (do sufitu 10 sesji - chunk NIGDY nie znika całkowicie, spec).
"""

import logging
import random
import statistics
from pathlib import Path

from sqlalchemy.orm import Session

from ..db import db_session
from ..models import Attempt, Chunk, ChunkExposure, SpeakingSession
from . import vad

logger = logging.getLogger(__name__)

# spec dodatek v2: sukces Trybu B = start < 1.5 s i brak ciszy dłuższej niż 2 s
EMBED_START_LATENCY_MAX_S = 1.5
EMBED_SILENCE_GAP_MAX_S = 2.0

BANK_B_PER_SESSION = 5
FAST_RT_MS = 500.0
FAST_STREAK_TO_PROMOTE = 3
MAX_INTERVAL_SESSIONS = 10
EMBED_MODE_FROM_SESSION = 4  # spec dodatek v2: Tryb B od 4. sesji


def current_session_number(db: Session) -> int:
    """Numer sesji, która się zaraz zacznie (1-indeksowany)."""
    return db.query(SpeakingSession).count() + 1


def embed_mode_unlocked(db: Session) -> bool:
    return current_session_number(db) >= EMBED_MODE_FROM_SESSION


def bank_a_chunks(db: Session, source_pack_id: int) -> list[Chunk]:
    return db.query(Chunk).filter(Chunk.bank == "domain", Chunk.source_pack_id == source_pack_id).all()


def pick_bank_b_chunks(db: Session, session_number: int, count: int = BANK_B_PER_SESSION) -> list[Chunk]:
    all_chunks = db.query(Chunk).filter(Chunk.bank == "function").all()
    if not all_chunks:
        return []
    due = [c for c in all_chunks if c.next_due_session is None or c.next_due_session <= session_number]
    if len(due) < count:
        rest = sorted(
            (c for c in all_chunks if c not in due),
            key=lambda c: c.next_due_session or 0,
        )
        due += rest[: count - len(due)]
    random.shuffle(due)
    return due[:count]


def update_schedule_after_session(db: Session, chunk: Chunk, session_number: int) -> None:
    """Wywoływane po zamknięciu sesji dla każdego chunku Banku B, który się w niej pojawił."""
    exposures = (
        db.query(ChunkExposure)
        .filter(
            ChunkExposure.chunk_id == chunk.id,
            ChunkExposure.mode == "access",
            ChunkExposure.rt_ms.isnot(None),
        )
        .order_by(ChunkExposure.id.desc())
        .limit(20)
        .all()
    )
    this_session_rts = [
        e.rt_ms for e in exposures
    ]  # ograniczone do najnowszych ekspozycji; w praktyce te z bieżącej sesji
    if not this_session_rts:
        return
    median_rt = statistics.median(this_session_rts[: BANK_B_PER_SESSION])

    if median_rt < FAST_RT_MS:
        chunk.consecutive_fast_exposures += 1
    else:
        chunk.consecutive_fast_exposures = 0

    if chunk.consecutive_fast_exposures >= FAST_STREAK_TO_PROMOTE:
        chunk.interval_sessions = min(chunk.interval_sessions * 2, MAX_INTERVAL_SESSIONS)
        chunk.consecutive_fast_exposures = 0
    else:
        chunk.interval_sessions = 1

    chunk.next_due_session = session_number + chunk.interval_sessions


def process_embed_attempt(attempt_id: int, chunk_exposure_id: int) -> None:
    """Tryb B (wszycie): tylko VAD, treść nie jest oceniana (spec dodatek v2).

    Sukces = start mowy < 1.5 s od t0 i brak ciszy > 2 s w kolejnych 10 s.
    Audio zawsze kasowane od razu - próba embed nigdy nie jest R1.
    """
    from ..models import User

    db = db_session()
    try:
        attempt = db.get(Attempt, attempt_id)
        exposure = db.get(ChunkExposure, chunk_exposure_id)
        if attempt is None or exposure is None or not attempt.audio_path:
            return

        path = Path(attempt.audio_path)
        audio = vad.read_wav_mono16k(path)
        t0_s = attempt.t0_offset_samples / vad.SAMPLE_RATE
        recording_end_s = len(audio) / vad.SAMPLE_RATE

        user = db.get(User, 1)
        threshold = user.vad_threshold if user else 0.5
        segments = vad.get_vad().speech_segments(audio, threshold=threshold)
        segs = [(max(s, t0_s), e) for s, e in segments if e > t0_s]

        start_latency = (segs[0][0] - t0_s) if segs else None
        max_gap = 0.0
        for (_, end_a), (start_b, _) in zip(segs, segs[1:]):
            max_gap = max(max_gap, start_b - end_a)
        if not segs:
            max_gap = recording_end_s - t0_s

        success = (
            start_latency is not None
            and start_latency < EMBED_START_LATENCY_MAX_S
            and max_gap <= EMBED_SILENCE_GAP_MAX_S
        )

        exposure.rt_ms = round(start_latency * 1000, 1) if start_latency is not None else None
        exposure.silence_exceeded = max_gap > EMBED_SILENCE_GAP_MAX_S
        exposure.success = success

        attempt.duration_s = round(recording_end_s, 2)
        attempt.status = "done"
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("Nie udało się usunąć %s", path)
        attempt.audio_path = None
        db.commit()
    except Exception:
        logger.exception("Przetwarzanie próby embed %s nie powiodło się", attempt_id)
        db.rollback()
        attempt = db.get(Attempt, attempt_id)
        if attempt:
            attempt.status = "error"
            db.commit()
    finally:
        db.close()
