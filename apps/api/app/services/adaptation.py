"""Adaptacja trudności (spec sekcja 9). Celowo prosta i przewidywalna.

Po każdych 5 próbach w module:
  m = mediana ttfw z ostatnich 5 prób
  m < 0.8 i brak fail  -> difficulty += 1
  m > 3.0 lub >= 2 fail -> difficulty -= 1
Trudność w [1, 10]. Limity czasowe stałe - presja czasu nie jest rozluźniana.
"""

import statistics

from sqlalchemy.orm import Session

from ..models import Attempt, ModuleState, TrainingSession, now_iso


def get_difficulty(db: Session, module: str) -> int:
    state = db.get(ModuleState, module)
    return state.difficulty if state else 1


def maybe_adapt(db: Session, session: TrainingSession) -> int | None:
    """Wywoływane po przetworzeniu próby. Zwraca nową trudność albo None."""
    attempts = (
        db.query(Attempt)
        .filter(Attempt.session_id == session.id, Attempt.status == "done")
        .order_by(Attempt.attempt_index)
        .all()
    )
    if len(attempts) == 0 or len(attempts) % 5 != 0:
        return None

    last5 = attempts[-5:]
    ttfws = [a.metrics.get("ttfw") for a in last5 if a.metrics and a.metrics.get("ttfw") is not None]
    fails = sum(1 for a in last5 if a.metrics and a.metrics.get("failed"))
    if not ttfws:
        return None

    m = statistics.median(ttfws)
    state = db.get(ModuleState, session.module)
    if state is None:
        state = ModuleState(module=session.module, difficulty=1)
        db.add(state)

    new = state.difficulty
    if m < 0.8 and fails == 0:
        new += 1
    elif m > 3.0 or fails >= 2:
        new -= 1
    new = max(1, min(10, new))

    if new != state.difficulty:
        state.difficulty = new
        state.updated_at = now_iso()
        db.commit()
        return new
    return None
