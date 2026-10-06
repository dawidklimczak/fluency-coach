"""Analiza nagrania rozmowy: VAD + whisper-1 na całości, metryki per tura.

Okno tury = od końca wypowiedzi rozmówcy (t0, znacznik z klienta) do końca
wypowiedzi użytkownika. Nagranie jest mikrofonem użytkownika (nie transkryptem
GPT-Live, który normalizuje zająknięcia i nie ma znaczników słów).
"""

import logging
from pathlib import Path

from ..db import db_session
from ..models import ConversationSession, ConversationTurn, User
from . import lang_metrics, metrics as metrics_svc, transcription, vad
from .attempt_pipeline import MIN_PHONATION_FOR_TRANSCRIPT_S, attach_punctuation
from .seed import language_config

logger = logging.getLogger(__name__)

# krótsze okno to back-channel lub szum, nie tura warta metryk
MIN_TURN_S = 1.0


def turn_metrics(
    segments: list[tuple[float, float]],
    words: list[dict] | None,
    window: tuple[float, float],
    fillers: list[str],
    repair_markers: list[str],
) -> dict:
    """Metryki jednej tury; segments i words w sekundach absolutnych nagrania."""
    t0, end = window
    segs = [(max(s, t0), min(e, end)) for s, e in segments if e > t0 and s < end]
    turn_words = [w for w in (words or []) if w["start"] >= t0 - 0.05 and w["end"] <= end + 0.05]
    text = " ".join(w["word"] for w in turn_words)

    clause_idx: set[int] = set()
    clause_conf = 0.0
    if text and turn_words:
        # indeksy względem słów tury, więc tekst i słowa muszą pochodzić z tego samego okna
        clause_idx, clause_conf = lang_metrics.clause_boundaries(text, turn_words)

    m = metrics_svc.compute_metrics(
        segments=segs,
        t0_s=t0,
        recording_end_s=end,
        words=turn_words,
        transcript=text,
        fillers=fillers,
        clause_boundary_indices=clause_idx,
        clause_segmentation_confidence=clause_conf,
    )
    if text:
        m.update(lang_metrics.compute_language_metrics(text, turn_words, repair_markers))
    m["transcript"] = text
    return m


def process_conversation(session_id: int, windows: list[tuple[float, float]]) -> None:
    db = db_session()
    try:
        session = db.get(ConversationSession, session_id)
        if session is None or not session.audio_path:
            return

        audio = vad.read_wav_mono16k(Path(session.audio_path))
        user = db.get(User, 1)
        threshold = user.vad_threshold if user else 0.5
        segments = vad.get_vad().speech_segments(audio, threshold=threshold)
        phonation = sum(e - s for s, e in segments)

        words = None
        transcript = None
        if phonation >= MIN_PHONATION_FOR_TRANSCRIPT_S:
            tr = transcription.transcribe(Path(session.audio_path))
            if tr:
                transcript = tr["text"]
                words = attach_punctuation(transcript, tr["words"])

        cfg = language_config()
        total_s = len(audio) / vad.SAMPLE_RATE
        number = 0
        for t0, end in windows:
            end = min(end, total_s)
            if end - t0 < MIN_TURN_S:
                continue
            number += 1
            m = turn_metrics(segments, words, (t0, end), cfg.get("fillers", []), cfg.get("repair_markers", []))
            db.add(ConversationTurn(
                session_id=session.id, number=number, start_s=round(t0, 3), end_s=round(end, 3),
                transcript=m.pop("transcript") or None, metrics=m,
            ))

        session.transcript = transcript
        session.status = "done"
        _finalize_audio(session)
        db.commit()
    except Exception:
        logger.exception("Przetwarzanie rozmowy %s nie powiodło się", session_id)
        db.rollback()
        session = db.get(ConversationSession, session_id)
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()


def _finalize_audio(session: ConversationSession) -> None:
    """Nagranie rozmowy jest długie i prywatne - kasujemy zaraz po analizie."""
    if not session.audio_path:
        return
    try:
        Path(session.audio_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Nie udało się usunąć %s", session.audio_path)
    session.audio_path = None

