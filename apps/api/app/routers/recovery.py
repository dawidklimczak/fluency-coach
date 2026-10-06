"""Recovery Drill (spec zmian §8): API dla krótkiego treningu odzyskiwania
kontroli nad wypowiedzią (lost_thread -> reformulation -> clarification_followup).
Bez osobnej tabeli "sesji" - to zestaw 2-3 samodzielnych RecoveryAttempt, tak
jak WritingRehearsal. Treść nigdy nie jest oceniana (spec §8.2).
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Attempt, FluencyMetrics, RecoveryAttempt, now_iso
from ..services import attempt_pipeline, recovery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recovery", tags=["recovery"])

STATIC_KINDS = ("lost_thread", "reformulation")


@router.get("/trials/{kind}")
def get_static_trial(kind: str, db: Session = Depends(get_db)):
    if kind not in STATIC_KINDS:
        raise HTTPException(422, f"kind musi być jednym z: {', '.join(STATIC_KINDS)}")
    return recovery.static_trial(db, kind)


def _save_upload(kind: str, attempt_id: int, data: bytes) -> str:
    audio_dir = get_settings().audio_dir / "recovery" / kind
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{attempt_id}.wav"
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


@router.post("/trials/{kind}/attempts", status_code=202)
async def create_recovery_attempt(
    kind: str,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    if kind not in STATIC_KINDS:
        raise HTTPException(422, f"kind musi być jednym z: {', '.join(STATIC_KINDS)}")
    try:
        meta = json.loads(payload)
        t0_offset_samples = int(meta.get("t0_offset_samples", 0))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    trial = recovery.static_trial(db, kind)
    ra = RecoveryAttempt(kind=kind, prompt=trial["prompt"])
    db.add(ra)
    db.flush()

    attempt = Attempt(
        recovery_attempt_id=ra.id, t0_iso=now_iso(), t0_offset_samples=t0_offset_samples, status="processing"
    )
    db.add(attempt)
    db.commit()
    attempt.audio_path = _save_upload(kind, attempt.id, await audio.read())
    ra.attempt_id = attempt.id
    db.commit()

    background.add_task(attempt_pipeline.process_attempt, attempt.id)
    return {"attempt_id": attempt.id, "recovery_attempt_id": ra.id}


@router.post("/follow-up")
def create_follow_up(body: dict, db: Session = Depends(get_db)):
    lost_thread_attempt_id = int(body.get("lost_thread_attempt_id", 0))
    source = db.get(Attempt, lost_thread_attempt_id)
    if source is None or source.recovery_attempt_id is None:
        raise HTTPException(404, "Nie ma takiej próby lost_thread")
    if source.status != "done":
        raise HTTPException(409, "Poprzednia próba jeszcze się przetwarza")

    question = recovery.generate_follow_up(source.transcript) or recovery.FALLBACK_FOLLOW_UP
    ra = RecoveryAttempt(kind="clarification_followup", prompt=question, follow_up_question=question)
    db.add(ra)
    db.commit()
    return {"recovery_attempt_id": ra.id, "question": question}


@router.post("/follow-up/{recovery_attempt_id}/attempts", status_code=202)
async def create_follow_up_attempt(
    recovery_attempt_id: int,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    ra = db.get(RecoveryAttempt, recovery_attempt_id)
    if ra is None or ra.kind != "clarification_followup":
        raise HTTPException(404, "Nie ma takiego follow-upu")
    try:
        meta = json.loads(payload)
        t0_offset_samples = int(meta.get("t0_offset_samples", 0))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    attempt = Attempt(
        recovery_attempt_id=ra.id, t0_iso=now_iso(), t0_offset_samples=t0_offset_samples, status="processing"
    )
    db.add(attempt)
    db.commit()
    attempt.audio_path = _save_upload("clarification_followup", attempt.id, await audio.read())
    ra.attempt_id = attempt.id
    db.commit()

    background.add_task(attempt_pipeline.process_attempt, attempt.id)
    return {"attempt_id": attempt.id}


@router.get("/attempts/{attempt_id}")
def get_recovery_attempt(attempt_id: int, db: Session = Depends(get_db)):
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "Nie ma takiej próby")
    fm = None
    if attempt.status == "done":
        fm = db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == attempt.id).first()
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "transcript": attempt.transcript if attempt.status == "done" else None,
    }
