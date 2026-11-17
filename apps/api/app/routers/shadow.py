"""Shadowing: fragment z nagraniem wzorcowym + analiza mówienia razem z lektorem.

Nagranie użytkownika trafia do pliku tymczasowego i jest kasowane po analizie.
"""

import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ShadowAttempt, ShadowPassage
from ..services import llm
from ..services import shadow as shadow_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shadow", tags=["shadow"])

SPEEDS = (0.75, 0.85, 1.0, 1.15)


def _get_passage(db: Session, passage_id: int) -> ShadowPassage:
    passage = db.get(ShadowPassage, passage_id)
    if passage is None:
        raise HTTPException(404, "Nie ma takiego fragmentu")
    return passage


@router.get("/next")
def next_passage(
    background: BackgroundTasks, exclude: int | None = None, db: Session = Depends(get_db)
):
    passage = shadow_svc.next_passage(db, exclude_id=exclude)
    if passage is None:
        if not llm.llm_enabled():
            raise HTTPException(503, "Brak klucza OpenAI - ustaw go w Ustawieniach")
        raise HTTPException(502, "Nie udało się przygotować fragmentu, spróbuj jeszcze raz")
    background.add_task(shadow_svc.ensure_stock)
    return shadow_svc.passage_payload(passage)


@router.get("/passages/{passage_id}/audio")
def passage_audio(passage_id: int, db: Session = Depends(get_db)):
    passage = _get_passage(db, passage_id)
    if not passage.audio_path or not Path(passage.audio_path).exists():
        raise HTTPException(404, "Brak nagrania dla tego fragmentu")
    return FileResponse(passage.audio_path, media_type="audio/mpeg")


@router.post("/passages/{passage_id}/attempts", status_code=202)
async def submit_attempt(
    passage_id: int,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    passage = _get_passage(db, passage_id)
    try:
        meta = json.loads(payload)
        with_text = bool(meta.get("with_text", True))
        speed = float(meta.get("speed", 1.0))
        offset_s = max(0.0, float(meta.get("offset_s", 0.0)))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")
    if speed not in SPEEDS:
        raise HTTPException(422, f"Prędkość musi być jedną z: {SPEEDS}")

    first = db.query(ShadowAttempt).filter(ShadowAttempt.passage_id == passage.id).count() == 0
    if first:
        passage.times_used += 1
    attempt = ShadowAttempt(passage_id=passage.id, with_text=with_text, speed=speed)
    db.add(attempt)
    db.commit()

    fd, temp_path = tempfile.mkstemp(suffix=".wav", prefix="shadow-")
    with open(fd, "wb") as f:
        f.write(await audio.read())
    background.add_task(shadow_svc.process_attempt, attempt.id, temp_path, offset_s)
    if first:
        background.add_task(shadow_svc.ensure_stock)
    return {"attempt_id": attempt.id}


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, db: Session = Depends(get_db)):
    attempt = db.get(ShadowAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "Nie ma takiego podejścia")
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "with_text": attempt.with_text,
        "speed": attempt.speed,
        "metrics": attempt.metrics if attempt.status == "done" else None,
        "words": attempt.words if attempt.status == "done" else None,
    }
