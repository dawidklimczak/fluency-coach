"""Przetwarzanie próby w tle: VAD -> Whisper -> metryki -> zmęczenie -> adaptacja.

Brak transkrypcji nigdy nie blokuje metryk czasowych (spec sekcja 8 i 14).
"""

import logging
import re
import statistics

from ..db import db_session
from ..models import Attempt, Task, TrainingSession
from . import adaptation, forbidden, metrics as metrics_svc, transcription, vad
from .seed import seed_config

logger = logging.getLogger(__name__)

FATIGUE_TTFW_RISE = 1.4  # +40% względem pierwszych 5 prób (spec 5.3)

# Whisper z promptem dysfluencyjnym halucynuje treść na ciszy (np. zapętlone
# "it's, it's, ..."). Obrona: (1) nie transkrybuj, gdy VAD nie widzi mowy,
# (2) odrzuć słowa, których timestampy nie pokrywają się z segmentami mowy.
MIN_PHONATION_FOR_TRANSCRIPT_S = 0.3
WORD_SEGMENT_TOLERANCE_S = 0.3


def filter_hallucinated_words(
    words: list[dict], segments: list[tuple[float, float]]
) -> list[dict]:
    """Zostawia tylko słowa nakładające się (z tolerancją) na segmenty mowy z VAD."""
    kept = []
    for w in words:
        ws = w["start"] - WORD_SEGMENT_TOLERANCE_S
        we = w["end"] + WORD_SEGMENT_TOLERANCE_S
        if any(ws < seg_end and we > seg_start for seg_start, seg_end in segments):
            kept.append(w)
    return kept


def attach_punctuation(transcript: str, words: list[dict]) -> list[dict]:
    """Whisper zwraca słowa bez interpunkcji; doklejamy ją z pełnego tekstu.

    Potrzebne do klasyfikacji pozycji pauzy (po znaku interpunkcyjnym = granica).
    """
    chunks = transcript.split()
    out = []
    ci = 0
    for w in words:
        word = w["word"].strip()
        attached = word
        # dopasuj sekwencyjnie token transkrypcji zawierający to słowo
        for j in range(ci, min(ci + 3, len(chunks))):
            plain = re.sub(r"[^\w']", "", chunks[j]).lower()
            if plain == re.sub(r"[^\w']", "", word).lower() and plain:
                attached = chunks[j]
                ci = j + 1
                break
        out.append({"word": attached, "start": w["start"], "end": w["end"]})
    return out


def detect_fatigue(attempts: list[Attempt]) -> bool:
    """Wzrost ttfw o 40% w ostatnich 3 próbach względem średniej z pierwszych 5."""
    done = [a for a in attempts if a.status == "done" and a.metrics]
    ttfws = [(a.attempt_index, a.metrics.get("ttfw")) for a in done]
    ttfws = [(i, t) for i, t in ttfws if t is not None]
    if len(ttfws) < 8:
        return False
    ttfws.sort(key=lambda x: x[0])
    baseline = statistics.mean(t for _, t in ttfws[:5])
    recent = statistics.median(t for _, t in ttfws[-3:])
    return baseline > 0 and recent > baseline * FATIGUE_TTFW_RISE


def process_attempt(attempt_id: int) -> None:
    db = db_session()
    try:
        attempt = db.get(Attempt, attempt_id)
        if attempt is None:
            return
        session = db.get(TrainingSession, attempt.session_id)
        task = db.get(Task, attempt.task_id)

        audio = vad.read_wav_mono16k(attempt.audio_path)
        t0_s = (attempt.metrics or {}).get("t0_offset_samples", 0) / vad.SAMPLE_RATE
        recording_end_s = len(audio) / vad.SAMPLE_RATE

        from ..models import User

        user = db.get(User, session.user_id) if session else None
        threshold = user.vad_threshold if user else 0.5

        segments = vad.get_vad().speech_segments(audio, threshold=threshold)

        phonation = sum(e - s for s, e in segments)
        transcript = None
        words = None
        if phonation >= MIN_PHONATION_FOR_TRANSCRIPT_S:
            tr = transcription.transcribe(attempt.audio_path)
            if tr:
                transcript = tr["text"]
                words = attach_punctuation(transcript, tr["words"])
                kept = filter_hallucinated_words(words, segments)
                if len(kept) < len(words):
                    logger.info(
                        "Odrzucono %d/%d słów poza segmentami mowy (halucynacja)",
                        len(words) - len(kept), len(words),
                    )
                    words = kept
                    transcript = " ".join(w["word"] for w in kept) if kept else None

        cfg = seed_config()
        m = metrics_svc.compute_metrics(
            segments=segments,
            t0_s=t0_s,
            recording_end_s=recording_end_s,
            words=words,
            transcript=transcript,
            fillers=cfg.get("fillers", []),
        )
        m["t0_offset_samples"] = (attempt.metrics or {}).get("t0_offset_samples", 0)

        # Describe Without the Word: użycie słowa zakazanego = fail
        if task and task.module == "describe_without_word" and transcript:
            fw = (task.payload or {}).get("forbidden_words", [])
            hits = forbidden.find_forbidden(transcript, fw)
            if hits:
                m["failed"] = True
                m["fail_reason"] = "forbidden_word"
                m["forbidden_hits"] = hits

        if transcript is None:
            m["transcript_missing"] = True

        attempt.transcript = transcript
        attempt.words = words
        attempt.vad_segments = [[round(s, 3), round(e, 3)] for s, e in segments]
        attempt.duration_s = round(recording_end_s, 2)
        attempt.metrics = m
        attempt.status = "done"
        db.commit()

        if session:
            all_attempts = (
                db.query(Attempt).filter(Attempt.session_id == session.id).all()
            )
            if detect_fatigue(all_attempts):
                attempt.metrics = {**m, "fatigue_detected": True}
                db.commit()
            adaptation.maybe_adapt(db, session)
    except Exception:
        logger.exception("Przetwarzanie próby %s nie powiodło się", attempt_id)
        db.rollback()
        attempt = db.get(Attempt, attempt_id)
        if attempt:
            attempt.status = "error"
            db.commit()
    finally:
        db.close()
