"""Wybór zadań do sesji: trudność docelowa +/-1, bez powtórek z ostatnich prób.

Zużycie puli: zadanie może pojawić się MAX_TASK_USES razy (pojawienie = jeden
przebieg drilla, rundy się nie liczą osobno), potem na stałe wypada z puli.
Świeżość utrzymuje automat dogenerowujący (task_gen.top_up_modules).
"""

import random

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Attempt, Task

MAX_TASK_USES = 3


def usage_counts(db: Session) -> dict[str, int]:
    """Liczba pojawień zadania = liczba różnych przebiegów drilla z próbą."""
    rows = (
        db.query(Attempt.task_id, func.count(func.distinct(Attempt.session_id)))
        .group_by(Attempt.task_id)
        .all()
    )
    return {task_id: count for task_id, count in rows}


def exhausted_task_ids(db: Session, max_uses: int = MAX_TASK_USES) -> set[str]:
    return {task_id for task_id, count in usage_counts(db).items() if count >= max_uses}


def pick_task(
    db: Session,
    module: str,
    difficulty: int,
    exclude_task_ids: set[str],
    structure_filter: str | None = None,
) -> Task | None:
    q = db.query(Task).filter(Task.module == module)
    if structure_filter:
        q = q.filter(Task.target_structure == structure_filter)
    candidates = q.all()

    # zadania zużyte (>= MAX_TASK_USES pojawień) wypadają z puli na stałe
    exhausted = exhausted_task_ids(db)
    candidates = [t for t in candidates if t.id not in exhausted]
    if not candidates:
        return None

    fresh = [t for t in candidates if t.id not in exclude_task_ids]
    pool = fresh or candidates

    for spread in (1, 2, 3, 10):
        near = [t for t in pool if abs(t.difficulty - difficulty) <= spread]
        if near:
            return random.choice(near)
    return random.choice(pool)


def recently_used_task_ids(db: Session, module: str, limit: int = 40) -> set[str]:
    rows = (
        db.query(Attempt.task_id)
        .join(Task, Task.id == Attempt.task_id)
        .filter(Task.module == module)
        .order_by(Attempt.id.desc())
        .limit(limit)
        .all()
    )
    return {r[0] for r in rows}
