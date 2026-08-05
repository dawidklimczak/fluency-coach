import statistics
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Attempt, Task, TrainingSession, now_iso
from ..services import adaptation, structure_mode as structure_mode_svc, task_select
from ..services.drills import available_modules, get_drill_config
from ..services.pipeline import detect_fatigue
from ..services.seed import structures as seed_structures

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionBody(BaseModel):
    module: str
    structure_filter: str | None = None
    learning_session_id: int | None = None


def _task_dict(task: Task, db: Session | None = None) -> dict:
    out = {
        "id": task.id,
        "module": task.module,
        "difficulty": task.difficulty,
        "target_structure": task.target_structure,
        "prompt_text": task.prompt_text,
        "payload": task.payload,
        "structure_mode": None,
        "structure_hint": None,
    }
    # tryb explicit/implicit rozstrzygany przy budowaniu sesji (spec 7.2);
    # w trybie jawnym frontend dostaje nazwę struktury i przykład z seed
    if task.target_structure and db is not None:
        mode = structure_mode_svc.choose_mode(db, task.target_structure)
        out["structure_mode"] = mode
        if mode == "explicit":
            s = next(
                (x for x in seed_structures() if x["id"] == task.target_structure),
                None,
            )
            if s:
                out["structure_hint"] = {
                    "label": s["label"],
                    "hint": s.get("hint"),
                    "example": s.get("example"),
                }
    return out


@router.post("")
def create_session(body: CreateSessionBody, db: Session = Depends(get_db)):
    try:
        cfg = get_drill_config(body.module)
    except KeyError:
        raise HTTPException(404, f"Nieznany moduł: {body.module}")

    difficulty = adaptation.get_difficulty(db, body.module)
    session = TrainingSession(
        user_id=1,
        module=body.module,
        target_difficulty=difficulty,
        structure_filter=body.structure_filter,
        learning_session_id=body.learning_session_id,
    )
    db.add(session)
    db.commit()

    exclude = task_select.recently_used_task_ids(db, body.module)
    task = task_select.pick_task(db, body.module, difficulty, exclude, body.structure_filter)
    if task is None:
        raise HTTPException(409, "Brak zadań dla tego modułu")

    return {
        "session_id": session.id,
        "module": body.module,
        "difficulty": difficulty,
        "first_task": _task_dict(task, db),
        "drill_config": cfg,
    }


@router.get("/{session_id}/next-task")
def next_task(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TrainingSession, session_id)
    if session is None:
        raise HTTPException(404, "Nie ma takiej sesji")
    cfg = get_drill_config(session.module)

    used_in_session = {
        r[0]
        for r in db.query(Attempt.task_id)
        .filter(Attempt.session_id == session_id)
        .all()
    }
    exclude = task_select.recently_used_task_ids(db, session.module) | used_in_session
    difficulty = adaptation.get_difficulty(db, session.module)
    task = task_select.pick_task(
        db, session.module, difficulty, exclude, session.structure_filter
    )
    if task is None:
        raise HTTPException(409, "Brak zadań")
    return {"task": _task_dict(task, db), "drill_config": cfg, "difficulty": difficulty}


@router.post("/{session_id}/end")
def end_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TrainingSession, session_id)
    if session is None:
        raise HTTPException(404, "Nie ma takiej sesji")

    attempts = (
        db.query(Attempt)
        .filter(Attempt.session_id == session_id, Attempt.status == "done")
        .order_by(Attempt.attempt_index)
        .all()
    )
    fatigue = detect_fatigue(attempts)
    if session.ended_at is None:
        session.ended_at = now_iso()
        session.ended_reason = "fatigue" if fatigue else (
            "completed" if attempts else "aborted"
        )
        db.commit()

    def metric_list(key: str) -> list:
        return [
            a.metrics[key]
            for a in attempts
            if a.metrics and a.metrics.get(key) is not None
        ]

    curve = [
        {
            "attempt_index": a.attempt_index,
            "ttfw": a.metrics.get("ttfw") if a.metrics else None,
            "filler_rate": a.metrics.get("filler_rate") if a.metrics else None,
        }
        for a in attempts
    ]

    ttfws = metric_list("ttfw")
    mlrs = metric_list("mean_length_of_run")
    summary = {
        "attempts": len(attempts),
        "median_ttfw": round(statistics.median(ttfws), 2) if ttfws else None,
        "median_mean_length_of_run": round(statistics.median(mlrs), 2) if mlrs else None,
        "long_pause_total": sum(metric_list("long_pause_count")) or 0,
        "fatigue_curve": curve,
    }

    # porównanie z medianą z ostatnich 7 dni (bez bieżącej sesji)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    prior = (
        db.query(Attempt)
        .join(TrainingSession, TrainingSession.id == Attempt.session_id)
        .filter(
            TrainingSession.module == session.module,
            Attempt.session_id != session_id,
            Attempt.status == "done",
            Attempt.created_at >= week_ago,
        )
        .all()
    )
    prior_ttfws = [
        a.metrics["ttfw"] for a in prior if a.metrics and a.metrics.get("ttfw") is not None
    ]
    baseline = round(statistics.median(prior_ttfws), 2) if prior_ttfws else None
    summary["baseline_7d_median_ttfw"] = baseline

    if fatigue:
        interpretation = (
            "Start time rose sharply near the end - that is cognitive fatigue, "
            "not regression. The session ended at the right moment."
        )
    elif baseline is not None and summary["median_ttfw"] is not None:
        if summary["median_ttfw"] < baseline * 0.9:
            interpretation = "Faster starts than your 7-day median."
        elif summary["median_ttfw"] > baseline * 1.1:
            interpretation = "Slower starts than usual - a single session, not a trend."
        else:
            interpretation = "Within your normal range from the last 7 days."
    else:
        interpretation = "Not enough history to compare - this builds your baseline."
    summary["interpretation"] = interpretation

    return {"summary": summary, "fatigue_detected": fatigue}


@router.get("/modules")
def modules(db: Session = Depends(get_db)):
    out = []
    for m in available_modules():
        m["difficulty"] = adaptation.get_difficulty(db, m["id"])
        out.append(m)
    return out


@router.get("/structures")
def structures_list(db: Session = Depends(get_db)):
    """Struktury dostępne w filtrze na ekranie startu - tylko te z zadaniami."""
    with_tasks = {
        r[0]
        for r in db.query(Task.target_structure)
        .filter(Task.target_structure.isnot(None))
        .distinct()
        .all()
    }
    return [
        {"id": s["id"], "label": s["label"]}
        for s in seed_structures()
        if s["id"] in with_tasks
    ]
