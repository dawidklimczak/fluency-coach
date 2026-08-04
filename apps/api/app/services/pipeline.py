"""Przetwarzanie próby w tle: VAD -> Whisper -> metryki -> zmęczenie -> adaptacja.

Brak transkrypcji nigdy nie blokuje metryk czasowych (spec sekcja 8 i 14).
"""

import logging
import re
import statistics

from ..db import db_session
from ..models import Attempt, Task, TrainingSession
from . import (
    adaptation,
    forbidden,
    indices,
    lang_metrics,
    llm,
    metrics as metrics_svc,
    structures as structures_svc,
    transcription,
    vad,
)
from .seed import seed_config

logger = logging.getLogger(__name__)

FATIGUE_TTFW_RISE = 1.4  # +40% względem pierwszych 5 prób (spec 5.3)

# Whisper z promptem dysfluencyjnym halucynuje treść na ciszy (np. zapętlone
# "it's, it's, ..."). Obrona: nie transkrybuj, gdy VAD nie widzi mowy.
# Celowo BEZ filtrowania słów po segmentach VAD - wycinało prawdziwe fragmenty
# wypowiedzi, gdy VAD przycinał cichszą mowę.
MIN_PHONATION_FOR_TRANSCRIPT_S = 0.3


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
        if (attempt.metrics or {}).get("structure_mode"):
            m["structure_mode"] = attempt.metrics["structure_mode"]

        if transcript:
            m.update(
                lang_metrics.compute_language_metrics(
                    transcript, words, cfg.get("repair_markers", [])
                )
            )

        m["complexity_fluency_tradeoff"] = indices.complexity_fluency_tradeoff(m)
        if session:
            m["automaticity_index"] = indices.automaticity_index(
                db, session.module, attempt.id, m
            )

        # metryki struktur 5.4 - tylko gdy zadanie wymaga struktury i jest transkrypcja
        if task and task.target_structure and transcript:
            m.update(
                structures_svc.structure_metrics(
                    task.target_structure, transcript, words
                )
            )

        # Paraphrase: dystans leksykalny między rundami tej samej próby (spec 7.1)
        if task and task.module == "paraphrase" and transcript and attempt.round_index > 1:
            prev_rounds = (
                db.query(Attempt)
                .filter(
                    Attempt.session_id == attempt.session_id,
                    Attempt.task_id == attempt.task_id,
                    Attempt.round_index < attempt.round_index,
                    Attempt.status == "done",
                )
                .order_by(Attempt.round_index)
                .all()
            )
            distances = [
                lang_metrics.lexical_distance(p.transcript, transcript)
                for p in prev_rounds
                if p.transcript
            ]
            distances = [d for d in distances if d is not None]
            if distances:
                m["lexical_distance_min"] = min(distances)
                # trzy wersje muszą mieć parami dystans > 0.5
                if attempt.round_index >= 3:
                    all_pairs = distances + [
                        d
                        for i, a in enumerate(prev_rounds)
                        for b in prev_rounds[i + 1 :]
                        if a.transcript and b.transcript
                        for d in [lang_metrics.lexical_distance(a.transcript, b.transcript)]
                        if d is not None
                    ]
                    m["paraphrase_pass"] = bool(all_pairs) and min(all_pairs) > 0.5

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

        # ocena jakościowa LLM po zapisaniu metryk (spec 8 pkt 2) - jej brak
        # ani opóźnienie nigdy nie blokują próby
        if task and transcript:
            try:
                from .drills import get_drill_config

                if get_drill_config(task.module).get("llm_eval"):
                    evaluation = llm.evaluate_attempt(
                        task.module, task.prompt_text, task.payload, transcript
                    )
                    if evaluation is not None:
                        attempt.llm_eval = evaluation
                        db.commit()
            except Exception:
                logger.exception("Ocena LLM nie powiodła się dla próby %s", attempt_id)
                db.rollback()

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
