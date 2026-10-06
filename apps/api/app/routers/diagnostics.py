"""Bottleneck Diagnostic (spec zmian §2): API dla sesji diagnostycznej
A(cold)/B(supplied_ideas)/C(self_plan)/D(repetition) + opcjonalna kontrola PL.
Wzorowane na routers/speaking_sessions.py (upload próby, przetwarzanie w tle,
polling), ale świadomie osobny router - żadne z tych danych nie trafiają do
/api/stats/progress ani do zwykłego Baseline.
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Attempt, DiagnosticSession, DiagnosticTrial, FluencyMetrics, now_iso
from ..services import attempt_pipeline, diagnostics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


def _session_or_404(db: Session, session_id: int) -> DiagnosticSession:
    session = db.get(DiagnosticSession, session_id)
    if session is None:
        raise HTTPException(404, "Nie ma takiej sesji diagnostycznej")
    return session


def _trial_dict(t: DiagnosticTrial) -> dict:
    return {
        "id": t.id,
        "condition": t.condition,
        "prompt": t.prompt,
        "support_json": t.support_json,
        "planning_seconds": t.planning_seconds,
        "speaking_limit_seconds": t.speaking_limit_seconds,
        "source_trial_id": t.source_trial_id,
        "order_in_session": t.order_in_session,
    }


def _session_payload(db: Session, session: DiagnosticSession, with_note: bool) -> dict:
    trials = (
        db.query(DiagnosticTrial)
        .filter(DiagnosticTrial.diagnostic_session_id == session.id)
        .order_by(DiagnosticTrial.order_in_session)
        .all()
    )
    return {
        "session_id": session.id,
        "status": session.status,
        "language_control_enabled": session.language_control_enabled,
        "trials": [_trial_dict(t) for t in trials],
        "note": diagnostics.session_note(db, session) if with_note else None,
    }


@router.post("/start")
def start_diagnostic(body: dict, db: Session = Depends(get_db)):
    language_control_enabled = bool(body.get("language_control_enabled", False))
    session = diagnostics.start_diagnostic_session(db, language_control_enabled)
    if session is None:
        raise HTTPException(503, "Nie udało się przygotować pytań - sprawdź klucz OpenAI w Ustawieniach")
    return _session_payload(db, session, with_note=False)


@router.get("/profile")
def get_bottleneck_profile(db: Session = Depends(get_db)):
    # musi być zarejestrowane PRZED /{session_id} - inaczej "profile" trafia
    # tam jako session_id i FastAPI zwraca 422 zamiast tego handlera
    profile = diagnostics.bottleneck_profile(db)
    return {"profile": profile}


@router.get("/{session_id}")
def get_diagnostic(session_id: int, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    return _session_payload(db, session, with_note=session.status == "completed")


@router.post("/{session_id}/plan")
def submit_plan(session_id: int, body: dict, db: Session = Depends(get_db)):
    _session_or_404(db, session_id)
    trial = db.get(DiagnosticTrial, int(body.get("trial_id", 0)))
    if trial is None or trial.diagnostic_session_id != session_id:
        raise HTTPException(404, "Nie ma takiego trialu")
    try:
        diagnostics.submit_plan(db, trial, body.get("items", []))
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return {"ok": True, "items": trial.support_json.get("items") if trial.support_json else []}


def _save_upload(session_id: int, condition: str, attempt_id: int, data: bytes) -> str:
    audio_dir = get_settings().audio_dir / "diagnostics" / str(session_id) / condition
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{attempt_id}.wav"
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def _process_trial_attempt(attempt_id: int, trial_id: int, skip_language_metrics: bool) -> None:
    attempt_pipeline.process_attempt(attempt_id, skip_language_metrics=skip_language_metrics)


@router.post("/{session_id}/trials/{condition}/attempts", status_code=202)
async def create_trial_attempt(
    session_id: int,
    condition: str,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    _session_or_404(db, session_id)
    trial = (
        db.query(DiagnosticTrial)
        .filter(DiagnosticTrial.diagnostic_session_id == session_id, DiagnosticTrial.condition == condition)
        .first()
    )
    if trial is None:
        raise HTTPException(404, "Nie ma takiego warunku w tej sesji")
    try:
        meta = json.loads(payload)
        t0_offset_samples = int(meta.get("t0_offset_samples", 0))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    attempt = Attempt(
        diagnostic_trial_id=trial.id, t0_iso=now_iso(), t0_offset_samples=t0_offset_samples, status="processing"
    )
    db.add(attempt)
    db.commit()
    attempt.audio_path = _save_upload(session_id, condition, attempt.id, await audio.read())
    trial.attempt_id = attempt.id
    db.commit()

    background.add_task(
        _process_trial_attempt, attempt.id, trial.id, condition == "native_control"
    )
    return {"attempt_id": attempt.id}


@router.get("/attempts/{attempt_id}")
def get_diagnostic_attempt(attempt_id: int, db: Session = Depends(get_db)):
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
        "phonation_time_ratio": fm.phonation_time_ratio if fm else None,
    }


@router.post("/{session_id}/end")
def end_diagnostic(session_id: int, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    if session.status != "completed":
        session.status = "completed"
        session.completed_at = now_iso()
        db.commit()
    return _session_payload(db, session, with_note=True)
