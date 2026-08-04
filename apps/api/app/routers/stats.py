import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Attempt, TrainingSession

router = APIRouter(prefix="/api/stats", tags=["stats"])

PROGRESS_KEYS = [
    "ttfw",
    "mean_length_of_run",
    "phonation_time_ratio",
    "long_pause_count",
    "mid_clause_pause_rate",
    "filler_rate",
    "complexity_fluency_tradeoff",
    "automaticity_index",
]


@router.get("/progress")
def progress(module: str, days: int = 30, db: Session = Depends(get_db)):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    attempts = (
        db.query(Attempt)
        .join(TrainingSession, TrainingSession.id == Attempt.session_id)
        .filter(
            TrainingSession.module == module,
            Attempt.status == "done",
            Attempt.created_at >= since,
        )
        .order_by(Attempt.created_at)
        .all()
    )

    by_day: dict[str, list[dict]] = defaultdict(list)
    for a in attempts:
        if a.metrics:
            by_day[a.created_at[:10]].append(a.metrics)

    series = []
    for day in sorted(by_day):
        row: dict = {"date": day, "attempts": len(by_day[day])}
        for key in PROGRESS_KEYS:
            vals = [m[key] for m in by_day[day] if m.get(key) is not None]
            row[key] = round(statistics.median(vals), 3) if vals else None
        series.append(row)

    return {"module": module, "days": days, "series": series}


@router.get("/structures")
def structures_heatmap(db: Session = Depends(get_db)):
    """Mapa cieplna (spec 7.2): avoidance, ttfw_structured vs bazowy,
    pre_structure_pause per struktura, plus avoidance jawny vs ukryty."""
    attempts = (
        db.query(Attempt).filter(Attempt.status == "done").all()
    )

    baseline_ttfws = [
        a.metrics["ttfw"]
        for a in attempts
        if a.metrics
        and a.metrics.get("ttfw") is not None
        and a.metrics.get("target_structure") is None
    ]
    baseline_ttfw = (
        round(statistics.median(baseline_ttfws), 3) if baseline_ttfws else None
    )

    by_structure: dict[str, list[dict]] = defaultdict(list)
    for a in attempts:
        m = a.metrics or {}
        if m.get("target_structure") and m.get("avoidance") is not None:
            by_structure[m["target_structure"]].append(m)

    rows = []
    for sid in sorted(by_structure):
        ms = by_structure[sid]

        def rate(subset: list[dict]) -> float | None:
            if not subset:
                return None
            return round(
                sum(1 for x in subset if x["avoidance"]) / len(subset), 3
            )

        ttfws = [x["ttfw"] for x in ms if x.get("ttfw") is not None]
        pauses = [
            x["pre_structure_pause"]
            for x in ms
            if x.get("pre_structure_pause") is not None
        ]
        rows.append(
            {
                "structure": sid,
                "attempts": len(ms),
                "avoidance": rate(ms),
                "avoidance_explicit": rate(
                    [x for x in ms if x.get("structure_mode") == "explicit"]
                ),
                "avoidance_implicit": rate(
                    [x for x in ms if x.get("structure_mode") == "implicit"]
                ),
                "ttfw_structured": (
                    round(statistics.median(ttfws), 3) if ttfws else None
                ),
                "pre_structure_pause": (
                    round(statistics.median(pauses), 3) if pauses else None
                ),
            }
        )

    return {"baseline_ttfw": baseline_ttfw, "structures": rows}
