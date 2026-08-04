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
