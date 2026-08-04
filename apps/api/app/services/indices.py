"""Wskaźniki złożone (spec 5.3).

automaticity_index: z-score wobec własnej historii użytkownika w module,
minimum 20 wcześniejszych prób - wcześniej status "kalibracja" (None).
cognitive_load_curve jest liczona przy podsumowaniu sesji (routers/sessions.py),
detekcja zmęczenia w pipeline.detect_fatigue.
"""

import statistics

from sqlalchemy.orm import Session

from ..models import Attempt, TrainingSession

MIN_HISTORY = 20

_Z_KEYS = ("ttfw", "mean_length_of_run", "mid_clause_pause_rate")


def _history_values(db: Session, module: str, exclude_attempt_id: int) -> dict[str, list[float]]:
    rows = (
        db.query(Attempt)
        .join(TrainingSession, TrainingSession.id == Attempt.session_id)
        .filter(
            TrainingSession.module == module,
            Attempt.status == "done",
            Attempt.id != exclude_attempt_id,
        )
        .all()
    )
    out: dict[str, list[float]] = {k: [] for k in _Z_KEYS}
    for a in rows:
        if not a.metrics:
            continue
        for k in _Z_KEYS:
            v = a.metrics.get(k)
            if v is not None:
                out[k].append(float(v))
    return out


def _z(value: float, history: list[float]) -> float | None:
    if len(history) < MIN_HISTORY:
        return None
    mean = statistics.mean(history)
    stdev = statistics.pstdev(history)
    if stdev < 1e-9:
        return 0.0
    return (value - mean) / stdev


def automaticity_index(db: Session, module: str, attempt_id: int, m: dict) -> float | None:
    """z(-ttfw) + z(mean_length_of_run) + z(-mid_clause_pause_rate).

    None, dopóki którakolwiek składowa nie ma 20 prób historii (kalibracja).
    """
    if any(m.get(k) is None for k in _Z_KEYS):
        return None
    hist = _history_values(db, module, attempt_id)
    z_ttfw = _z(m["ttfw"], hist["ttfw"])
    z_mlr = _z(m["mean_length_of_run"], hist["mean_length_of_run"])
    z_mcp = _z(m["mid_clause_pause_rate"], hist["mid_clause_pause_rate"])
    if z_ttfw is None or z_mlr is None or z_mcp is None:
        return None
    return round(-z_ttfw + z_mlr - z_mcp, 3)


def complexity_fluency_tradeoff(m: dict) -> float | None:
    """subordination_index / mean_length_of_run. System ma go obniżać."""
    si = m.get("subordination_index")
    mlr = m.get("mean_length_of_run")
    if si is None or not mlr:
        return None
    return round(si / mlr, 4)
