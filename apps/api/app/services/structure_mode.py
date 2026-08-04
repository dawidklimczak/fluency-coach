"""Dobór trybu explicit/implicit dla zadania ze strukturą (spec 7.2).

Dopóki avoidance w trybie jawnym > 0.2, 80% zadań jest jawnych; poniżej progu
proporcja odwraca się na 30/70 na rzecz ukrytych. Tryb nie jest cechą zadania -
rozstrzygnięcie trafia do attempts.metrics.
"""

import random

from sqlalchemy.orm import Session

from ..models import Attempt

EXPLICIT_AVOIDANCE_THRESHOLD = 0.2
MIN_EXPLICIT_ATTEMPTS = 5
HISTORY_WINDOW = 20


def explicit_avoidance(db: Session, structure_id: str) -> float | None:
    """Odsetek unikania w ostatnich próbach jawnych z tą strukturą."""
    rows = (
        db.query(Attempt)
        .filter(Attempt.status == "done")
        .order_by(Attempt.id.desc())
        .limit(500)
        .all()
    )
    vals = []
    for a in rows:
        m = a.metrics or {}
        if (
            m.get("target_structure") == structure_id
            and m.get("structure_mode") == "explicit"
            and m.get("avoidance") is not None
        ):
            vals.append(1.0 if m["avoidance"] else 0.0)
            if len(vals) >= HISTORY_WINDOW:
                break
    if len(vals) < MIN_EXPLICIT_ATTEMPTS:
        return None
    return sum(vals) / len(vals)


def choose_mode(db: Session, structure_id: str) -> str:
    av = explicit_avoidance(db, structure_id)
    if av is None or av > EXPLICIT_AVOIDANCE_THRESHOLD:
        explicit_share = 0.8
    else:
        explicit_share = 0.3
    return "explicit" if random.random() < explicit_share else "implicit"
