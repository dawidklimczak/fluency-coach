"""Postęp: wyłącznie na podstawie sond transferowych (spec §3 - "Faza 4 jest
jedynym prawdziwym pomiarem. Tylko jej metryki idą na wykres postępu.").

Delta względem Baseline (mediana krocząca, okno 10 sond) jest liczona przy
zdejmowaniu/przywracaniu wsparcia (spec §4, §6) - tutaj tylko surowe wartości
dzienne, prezentacja delty należy do frontendu tego ekranu (spec §5:
"wyłącznie delta vs baseline... bez z-score'ów, bez ocen").
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Attempt, FluencyMetrics, TransferProbe

router = APIRouter(prefix="/api/stats", tags=["stats"])

PROGRESS_KEYS = [
    "mean_length_of_run",
    "phonation_time_ratio",
    "mid_clause_pause_duration",
    "mid_clause_pause_frequency",
    "clause_final_pause_duration",
    "articulation_rate",
]


@router.get("/progress")
def progress(days: int = 90, probe_type: str = "far", db: Session = Depends(get_db)):
    if probe_type not in ("near", "far", "legacy"):
        probe_type = "far"
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (
        db.query(TransferProbe, FluencyMetrics, Attempt)
        .join(Attempt, Attempt.id == TransferProbe.attempt_id)
        .join(FluencyMetrics, FluencyMetrics.attempt_id == Attempt.id)
        .filter(
            Attempt.status == "done",
            TransferProbe.created_at >= since,
            TransferProbe.probe_type == probe_type,
        )
        .order_by(TransferProbe.created_at)
        .all()
    )

    by_day: dict[str, list[FluencyMetrics]] = defaultdict(list)
    for probe, fm, _attempt in rows:
        by_day[probe.created_at[:10]].append(fm)

    series = []
    for day in sorted(by_day):
        entries = by_day[day]
        row: dict = {"date": day, "probes": len(entries)}
        for key in PROGRESS_KEYS:
            vals = [getattr(fm, key) for fm in entries if getattr(fm, key) is not None]
            row[key] = round(statistics.median(vals), 3) if vals else None
        series.append(row)

    return {"days": days, "probe_type": probe_type, "series": series}
