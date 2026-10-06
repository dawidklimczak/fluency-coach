"""Przetwarzanie próby w tle: VAD -> Whisper -> metryki -> FluencyMetrics.

Zastępuje usunięty pipeline.py (był zbudowany wokół starego modelu Attempt).
Audio jest kasowane od razu po analizie (spec §6), z wyjątkiem R1, dla którego
zostaje żywe do audio_expires_at (zadanie własnej transkrypcji, dodatek v2).
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..db import db_session
from ..models import Attempt, FluencyMetrics, Round, User
from . import lang_metrics, metrics as metrics_svc, transcription, vad
from .seed import language_config

logger = logging.getLogger(__name__)

MIN_PHONATION_FOR_TRANSCRIPT_S = 0.3
SELF_TRANSCRIPTION_WINDOW_HOURS = 24

_CARRIER_KEYS = {
    "articulation_rate", "mean_length_of_run", "phonation_time_ratio",
    "mid_clause_pause_duration", "mid_clause_pause_frequency",
    "clause_final_pause_duration", "clause_final_pause_frequency",
    "ttfw", "clause_segmentation_confidence",
}


def attach_punctuation(transcript: str, words: list[dict]) -> list[dict]:
    """Whisper zwraca słowa bez interpunkcji; doklejamy ją z pełnego tekstu -
    potrzebne do klasyfikacji pozycji pauzy."""
    chunks = transcript.split()
    out = []
    ci = 0
    for w in words:
        word = w["word"].strip()
        attached = word
        for j in range(ci, min(ci + 3, len(chunks))):
            plain = re.sub(r"[^\w']", "", chunks[j]).lower()
            if plain == re.sub(r"[^\w']", "", word).lower() and plain:
                attached = chunks[j]
                ci = j + 1
                break
        out.append({"word": attached, "start": w["start"], "end": w["end"]})
    return out


def _is_round_one(db, attempt: Attempt) -> bool:
    if attempt.round_id is None:
        return False
    r = db.get(Round, attempt.round_id)
    return bool(r and r.number == 1)


def _finalize_audio(db, attempt: Attempt) -> None:
    """Kasuje audio od razu, chyba że to R1 - wtedy zostaje do 24h (dodatek v2)."""
    if not attempt.audio_path:
        return
    path = Path(attempt.audio_path)
    if _is_round_one(db, attempt):
        attempt.audio_expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=SELF_TRANSCRIPTION_WINDOW_HOURS)
        ).isoformat()
        return
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("Nie udało się usunąć %s", path)
    attempt.audio_path = None


def process_attempt(attempt_id: int, skip_language_metrics: bool = False) -> None:
    """skip_language_metrics=True (Bottleneck Diagnostic, kontrola native-language,
    spec zmian §2.3): pomija lang_metrics/clause_boundaries, bo obie zależą od
    spaCy en_core_web_sm i zakładają angielski - próba po polsku dostaje tylko
    metryki czasowe (VAD/Whisper), niezależne od języka."""
    db = db_session()
    try:
        attempt = db.get(Attempt, attempt_id)
        if attempt is None or not attempt.audio_path:
            return

        audio = vad.read_wav_mono16k(Path(attempt.audio_path))
        t0_s = attempt.t0_offset_samples / vad.SAMPLE_RATE
        recording_end_s = len(audio) / vad.SAMPLE_RATE

        user = db.get(User, 1)
        threshold = user.vad_threshold if user else 0.5
        segments = vad.get_vad().speech_segments(audio, threshold=threshold)
        phonation = sum(e - s for s, e in segments)

        transcript = None
        words = None
        if phonation >= MIN_PHONATION_FOR_TRANSCRIPT_S:
            tr = transcription.transcribe(Path(attempt.audio_path))
            if tr:
                transcript = tr["text"]
                words = attach_punctuation(transcript, tr["words"])

        cfg = language_config()
        clause_idx: set[int] = set()
        clause_conf = 0.0
        if transcript and words and not skip_language_metrics:
            clause_idx, clause_conf = lang_metrics.clause_boundaries(transcript, words)

        m = metrics_svc.compute_metrics(
            segments=segments,
            t0_s=t0_s,
            recording_end_s=recording_end_s,
            words=words,
            transcript=transcript,
            fillers=cfg.get("fillers", []),
            clause_boundary_indices=clause_idx,
            clause_segmentation_confidence=clause_conf,
        )
        lang_extra: dict = {}
        if transcript and not skip_language_metrics:
            lang_extra = lang_metrics.compute_language_metrics(
                transcript, words, cfg.get("repair_markers", [])
            )

        attempt.transcript = transcript
        attempt.words = words
        attempt.vad_segments = [[round(s, 3), round(e, 3)] for s, e in segments]
        attempt.duration_s = round(recording_end_s, 2)
        attempt.status = "done"

        combined = {**m, **lang_extra}
        fm_kwargs = {k: combined.get(k) for k in _CARRIER_KEYS if k in combined}
        # filler/wypełniacze: wyłącznie opisowe, nigdy karane (poprawka v2A) -
        # osobne pole żeby nie dało się go pomylić z metryką nośną dla reguł
        fm_kwargs["filled_pause_rate"] = combined.get("filler_rate")
        extra = {
            k: v for k, v in combined.items()
            if k not in _CARRIER_KEYS and k != "filler_rate"
        }
        db.add(FluencyMetrics(attempt_id=attempt.id, extra=extra, **fm_kwargs))

        _finalize_audio(db, attempt)
        db.commit()
    except Exception:
        logger.exception("Przetwarzanie próby %s nie powiodło się", attempt_id)
        db.rollback()
        attempt = db.get(Attempt, attempt_id)
        if attempt:
            attempt.status = "error"
            db.commit()
    finally:
        db.close()
