"""Sesje nauki: otwierane przez użytkownika, mieszczą dowolną liczbę przebiegów
drilli. Zamknięcie liczy podsumowanie, feedback LLM (też gramatyczny - zawsze
po sesji, nigdy w trakcie) i aktualizuje ciągłą diagnozę w Observations."""

import json
import logging
import statistics

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Attempt,
    LearningSession,
    Observation,
    TrainingSession,
    now_iso,
)
from ..services import llm, task_gen

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/learning-sessions", tags=["learning-sessions"])

MAX_FEEDBACK_TRANSCRIPT_CHARS = 20000


def _open_session(db: Session) -> LearningSession | None:
    return (
        db.query(LearningSession)
        .filter(LearningSession.ended_at.is_(None))
        .order_by(LearningSession.id.desc())
        .first()
    )


def _session_attempts(db: Session, ls_id: int) -> list[Attempt]:
    return (
        db.query(Attempt)
        .join(TrainingSession, TrainingSession.id == Attempt.session_id)
        .filter(
            TrainingSession.learning_session_id == ls_id,
            Attempt.status == "done",
        )
        .order_by(Attempt.id)
        .all()
    )


def _state(db: Session, ls: LearningSession) -> dict:
    attempts = _session_attempts(db, ls.id)
    modules = sorted(
        {
            r[0]
            for r in db.query(TrainingSession.module)
            .filter(TrainingSession.learning_session_id == ls.id)
            .all()
        }
    )
    fatigue = any(a.metrics and a.metrics.get("fatigue_detected") for a in attempts)
    return {
        "id": ls.id,
        "number": ls.id,
        "started_at": ls.started_at,
        "attempts": len(attempts),
        "modules_done": modules,
        "fatigue_detected": fatigue,
    }


@router.post("")
def start(db: Session = Depends(get_db)):
    existing = _open_session(db)
    if existing is not None:
        return {**_state(db, existing), "resumed": True}
    ls = LearningSession()
    db.add(ls)
    db.commit()
    return {**_state(db, ls), "resumed": False}


@router.get("/current")
def current(db: Session = Depends(get_db)):
    ls = _open_session(db)
    if ls is None:
        return {"open": False}
    return {"open": True, **_state(db, ls)}


def _metric_median(attempts: list[Attempt], key: str) -> float | None:
    vals = [
        a.metrics[key]
        for a in attempts
        if a.metrics and a.metrics.get(key) is not None
    ]
    return round(statistics.median(vals), 2) if vals else None


def _build_summary(db: Session, ls: LearningSession) -> dict:
    attempts = _session_attempts(db, ls.id)
    runs = (
        db.query(TrainingSession)
        .filter(TrainingSession.learning_session_id == ls.id)
        .all()
    )
    by_module: dict[str, list[Attempt]] = {}
    run_module = {r.id: r.module for r in runs}
    for a in attempts:
        by_module.setdefault(run_module.get(a.session_id, "?"), []).append(a)

    modules = [
        {
            "module": module,
            "attempts": len(items),
            "median_ttfw": _metric_median(items, "ttfw"),
            "median_mean_length_of_run": _metric_median(items, "mean_length_of_run"),
            "long_pause_total": sum(
                a.metrics.get("long_pause_count") or 0 for a in items if a.metrics
            ),
        }
        for module, items in sorted(by_module.items())
    ]

    curve = [
        {
            "index": i + 1,
            "ttfw": a.metrics.get("ttfw") if a.metrics else None,
            "filler_rate": a.metrics.get("filler_rate") if a.metrics else None,
        }
        for i, a in enumerate(attempts)
    ]

    return {
        "number": ls.id,
        "started_at": ls.started_at,
        "ended_at": now_iso(),
        "attempts": len(attempts),
        "modules": modules,
        "median_ttfw": _metric_median(attempts, "ttfw"),
        "fatigue_detected": any(
            a.metrics and a.metrics.get("fatigue_detected") for a in attempts
        ),
        "fatigue_curve": curve,
    }


def _session_feedback(summary: dict, transcripts: list[str]) -> dict | None:
    if not transcripts or not llm.llm_enabled():
        return None
    digest = {
        "attempts": summary["attempts"],
        "modules": summary["modules"],
        "median_ttfw_s": summary["median_ttfw"],
        "fatigue_detected": summary["fatigue_detected"],
    }
    result = llm.complete_json(
        "session_feedback",
        {
            "metrics_digest": json.dumps(digest, ensure_ascii=False),
            "transcripts": "\n---\n".join(transcripts)[:MAX_FEEDBACK_TRANSCRIPT_CHARS],
        },
        llm.SessionFeedback,
    )
    return result.model_dump() if result is not None else None


def _update_observations(
    db: Session, transcripts: list[str], feedback: dict | None
) -> None:
    """Ciągła diagnoza: scala dotychczasowe obserwacje z materiałem z tej sesji."""
    if not transcripts or not llm.llm_enabled():
        return
    latest = db.query(Observation).order_by(Observation.id.desc()).first()
    previous = latest.items if latest and latest.items else []
    grammar = (feedback or {}).get("grammar", [])
    result = llm.complete_json(
        "observations",
        {
            "previous_items": json.dumps(previous, ensure_ascii=False),
            "transcripts": "\n---\n".join(transcripts)[:MAX_FEEDBACK_TRANSCRIPT_CHARS],
            "session_grammar": json.dumps(grammar, ensure_ascii=False),
        },
        llm.ObservationsResult,
    )
    if result is not None:
        db.add(
            Observation(
                period_start=latest.period_end if latest else now_iso(),
                period_end=now_iso(),
                items=[i.model_dump() for i in result.items],
            )
        )
        db.commit()


@router.post("/{ls_id}/end")
def end(ls_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    ls = db.get(LearningSession, ls_id)
    if ls is None:
        raise HTTPException(404, "Nie ma takiej sesji nauki")

    # domknij otwarte przebiegi drilli
    for run in (
        db.query(TrainingSession)
        .filter(
            TrainingSession.learning_session_id == ls_id,
            TrainingSession.ended_at.is_(None),
        )
        .all()
    ):
        run.ended_at = now_iso()
        run.ended_reason = run.ended_reason or "completed"

    summary = _build_summary(db, ls)
    transcripts = [
        a.transcript for a in _session_attempts(db, ls_id) if a.transcript
    ]

    feedback = None
    try:
        feedback = _session_feedback(summary, transcripts)
    except Exception:
        logger.exception("Feedback LLM dla sesji %s nie powiódł się", ls_id)
    summary["feedback"] = feedback

    if ls.ended_at is None:
        ls.ended_at = summary["ended_at"]
        ls.summary = summary
        db.commit()
        try:
            _update_observations(db, transcripts, feedback)
        except Exception:
            logger.exception("Aktualizacja obserwacji po sesji %s nie powiodła się", ls_id)
        # automat: uzupełnij w tle pulę zadań dla używanych modułów (spec 8 pkt 1)
        used_modules = [m["module"] for m in summary["modules"]]
        if used_modules:
            background.add_task(task_gen.top_up_modules, used_modules)
    else:
        summary = ls.summary or summary

    return {"summary": summary}
