"""Wybór zadań do sesji: trudność docelowa +/-1, bez powtórek z ostatnich prób."""

import random

from sqlalchemy.orm import Session

from ..models import Attempt, Task


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
