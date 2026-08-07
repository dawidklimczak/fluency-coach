"""Trener tempa czytania: nagranie + tekst wzorcowy -> tempo, mapa i dokładność.

Nagranie jest przetwarzane w pliku tymczasowym i kasowane od razu po analizie -
ten moduł nie zostawia audio na dysku.
"""

import json
import logging
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import db_session, get_db
from ..models import ReadingAttempt, User
from ..services import llm, reading as reading_svc, transcription, vad
from ..services.seed import structures as seed_structures

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reading", tags=["reading"])

MAX_REFERENCE_CHARS = 6000
MIN_TARGET_WPM = 60
MAX_TARGET_WPM = 300

MAX_STRUCTURES = 3  # więcej naraz i tekst robi się sztuczny


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


class GenerateBody(BaseModel):
    minutes: float = Field(ge=0.5, le=10)
    target_wpm: int = Field(default=130, ge=MIN_TARGET_WPM, le=MAX_TARGET_WPM)
    topic: str = ""
    structures: list[str] = []


def _structure_instruction(structure_ids: list[str]) -> str:
    """Opis wybranych struktur dla promptu - z etykiet i przykładów z seed."""
    if not structure_ids:
        return "No particular grammatical structure is required."
    known = {s["id"]: s for s in seed_structures()}
    lines = []
    for sid in structure_ids:
        s = known.get(sid)
        if s is None:
            continue
        lines.append(f'- {s["label"]} ({s.get("hint", "")}). Example: {s.get("example", "")}')
    if not lines:
        return "No particular grammatical structure is required."
    return (
        "Weave these grammatical structures into the passage so each appears "
        "several times, always in a way that reads naturally:\n" + "\n".join(lines)
    )


def _strip_digits_warning(text: str) -> bool:
    """Cyfry psułyby dopasowanie: Whisper zapisze 1995 jako 'nineteen ninety five'."""
    return bool(re.search(r"\d", text))


@router.post("/generate")
def generate_text(body: GenerateBody):
    if not llm.llm_enabled():
        raise HTTPException(503, "Brak klucza OpenAI - ustaw go w Ustawieniach")

    known_ids = {s["id"] for s in seed_structures()}
    unknown = [s for s in body.structures if s not in known_ids]
    if unknown:
        raise HTTPException(404, f"Nieznane struktury: {', '.join(unknown)}")
    if len(body.structures) > MAX_STRUCTURES:
        raise HTTPException(422, f"Najwyżej {MAX_STRUCTURES} struktury naraz")

    word_count = max(40, round(body.minutes * body.target_wpm))
    result = llm.complete_json(
        "generate_reading_text",
        {
            "topic": body.topic.strip() or "anything interesting from everyday adult life",
            "word_count": str(word_count),
            "structure_instruction": _structure_instruction(body.structures),
        },
        llm.GeneratedReadingText,
    )
    if result is None:
        raise HTTPException(502, "Nie udało się wygenerować tekstu")

    text = result.text.strip()
    actual_words = len(text.split())
    return {
        "title": result.title.strip(),
        "text": text,
        "word_count": actual_words,
        "requested_words": word_count,
        "estimated_seconds": round(actual_words / body.target_wpm * 60),
        # ostrzeżenie, nie błąd: cyfry zaniżą dokładność, ale tekst da się czytać
        "contains_digits": _strip_digits_warning(text),
    }


@router.get("/structures")
def available_structures():
    """Wszystkie struktury do wyboru przy generowaniu - także te bez zadań."""
    return [{"id": s["id"], "label": s["label"]} for s in seed_structures()]


# UWAGA: ta trasa musi zostać PO /structures, inaczej przechwyci ją jako id
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
