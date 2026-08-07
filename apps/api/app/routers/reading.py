"""Trener tempa czytania: nagranie + tekst wzorcowy -> tempo, mapa i dokładność.

Nagranie jest przetwarzane w pliku tymczasowym i kasowane od razu po analizie -
ten moduł nie zostawia audio na dysku.
"""

import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import db_session, get_db
from ..models import ReadingAttempt
from ..services import reading as reading_svc, transcription, vad
from ..models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reading", tags=["reading"])

MAX_REFERENCE_CHARS = 6000
MIN_TARGET_WPM = 60
MAX_TARGET_WPM = 300


def _process(reading_id: int, audio_path: str) -> None:
    db = db_session()
    path = Path(audio_path)
    try:
        attempt = db.get(ReadingAttempt, reading_id)
        if attempt is None:
            return

        audio = vad.read_wav_mono16k(path)
        duration_s = len(audio) / vad.SAMPLE_RATE

        user = db.get(User, 1)
        threshold = user.vad_threshold if user else 0.5
        segments = vad.get_vad().speech_segments(audio, threshold=threshold)
        phonation_s = sum(end - start for start, end in segments)

        # pusty prompt: przy czytaniu nie podpowiadamy Whisperowi niczego,
        # żeby nie "usłyszał" tekstu, którego użytkownik nie wypowiedział
        result = transcription.transcribe(path, prompt="")
        transcript = result["text"] if result else ""
        spoken = result["words"] if result else []

        tokens, metrics = reading_svc.compute(
            reference_text=attempt.reference_text,
            spoken_words=spoken,
            transcript=transcript,
            duration_s=duration_s,
            phonation_s=phonation_s,
            target_wpm=attempt.target_wpm,
        )

        attempt.transcript = transcript or None
        attempt.duration_s = round(duration_s, 2)
        attempt.words = tokens
        attempt.metrics = metrics
        attempt.status = "done"
        db.commit()
    except Exception:
        logger.exception("Analiza czytania %s nie powiodła się", reading_id)
        db.rollback()
        attempt = db.get(ReadingAttempt, reading_id)
        if attempt:
            attempt.status = "error"
            db.commit()
    finally:
        db.close()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Nie udało się usunąć pliku tymczasowego %s", path)


@router.post("", status_code=202)
async def create_reading(
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        meta = json.loads(payload)
        reference_text = str(meta["reference_text"]).strip()
        target_wpm = int(meta.get("target_wpm", 130))
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    if not reference_text:
        raise HTTPException(422, "Brak tekstu do przeczytania")
    if len(reference_text) > MAX_REFERENCE_CHARS:
        raise HTTPException(422, f"Tekst dłuższy niż {MAX_REFERENCE_CHARS} znaków")
    if not MIN_TARGET_WPM <= target_wpm <= MAX_TARGET_WPM:
        raise HTTPException(422, "Tempo docelowe poza zakresem 60-300")

    attempt = ReadingAttempt(
        reference_text=reference_text, target_wpm=target_wpm, status="processing"
    )
    db.add(attempt)
    db.commit()

    fd, temp_path = tempfile.mkstemp(suffix=".wav", prefix="reading-")
    with open(fd, "wb") as f:
        f.write(await audio.read())

    background.add_task(_process, attempt.id, temp_path)
    return {"reading_id": attempt.id}


@router.get("/{reading_id}")
def get_reading(reading_id: int, db: Session = Depends(get_db)):
    attempt = db.get(ReadingAttempt, reading_id)
    if attempt is None:
        raise HTTPException(404, "Nie ma takiej próby czytania")
    return {
        "reading_id": attempt.id,
        "status": attempt.status,
        "target_wpm": attempt.target_wpm,
        "metrics": attempt.metrics if attempt.status == "done" else None,
        "words": attempt.words if attempt.status == "done" else None,
        "transcript": attempt.transcript if attempt.status == "done" else None,
    }


@router.get("")
def recent(limit: int = 10, db: Session = Depends(get_db)):
    """Historia tempa - do pokazania, czy czytanie przyspiesza w czasie."""
    rows = (
        db.query(ReadingAttempt)
        .filter(ReadingAttempt.status == "done")
        .order_by(ReadingAttempt.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "reading_id": r.id,
            "created_at": r.created_at,
            "target_wpm": r.target_wpm,
            "wpm": (r.metrics or {}).get("wpm"),
            "accuracy": (r.metrics or {}).get("accuracy"),
            "words_read": (r.metrics or {}).get("words_read"),
        }
        for r in reversed(rows)
    ]
