import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Attempt, TrainingSession, now_iso
from ..services.pipeline import process_attempt

router = APIRouter(prefix="/api/attempts", tags=["attempts"])


@router.post("", status_code=202)
async def create_attempt(
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        meta = json.loads(payload)
        session_id = int(meta["session_id"])
        task_id = str(meta["task_id"])
        t0_offset_samples = int(meta.get("t0_offset_samples", 0))
        attempt_index = int(meta.get("attempt_index", 1))
        round_index = int(meta.get("round_index", 1))
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    session = db.get(TrainingSession, session_id)
    if session is None:
        raise HTTPException(404, "Nie ma takiej sesji")

    attempt = Attempt(
        session_id=session_id,
        task_id=task_id,
        attempt_index=attempt_index,
        round_index=round_index,
        t0_iso=meta.get("t0_iso") or now_iso(),
        status="processing",
        metrics={"t0_offset_samples": t0_offset_samples},
    )
    db.add(attempt)
    db.commit()

    audio_dir = get_settings().audio_dir / str(session_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"{attempt.id}.wav"
    with open(audio_path, "wb") as f:
        f.write(await audio.read())
    attempt.audio_path = str(audio_path)
    db.commit()

    background.add_task(process_attempt, attempt.id)
    return {"attempt_id": attempt.id}


@router.get("/{attempt_id}")
def get_attempt(attempt_id: int, db: Session = Depends(get_db)):
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "Nie ma takiej próby")
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "metrics": attempt.metrics if attempt.status == "done" else None,
        "transcript": attempt.transcript if attempt.status == "done" else None,
        "llm_eval": attempt.llm_eval,
    }
