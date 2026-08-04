import json
from functools import lru_cache

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ModuleState, Task, User


@lru_cache
def seed_file() -> dict:
    path = get_settings().seed_tasks_path
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed_config() -> dict:
    """Sekcja config z seed_tasks.json: fillers, repair_markers, progi pauz, prompt Whispera."""
    return seed_file().get("config", {})


def structures() -> list[dict]:
    return seed_file().get("structures", [])


def ensure_seeded(db: Session) -> None:
    if db.query(User).count() == 0:
        db.add(User(id=1))

    data = seed_file()
    existing = {row[0] for row in db.query(Task.id).all()}
    for t in data.get("tasks", []):
        if t["id"] in existing:
            continue
        db.add(
            Task(
                id=t["id"],
                module=t["module"],
                difficulty=t["difficulty"],
                target_structure=t.get("target_structure"),
                structure_mode=None,
                prompt_text=t["prompt_text"],
                payload=t.get("payload"),
                tags=t.get("tags"),
                source="seed",
            )
        )

    modules = {t["module"] for t in data.get("tasks", [])}
    existing_states = {row[0] for row in db.query(ModuleState.module).all()}
    for m in modules:
        if m not in existing_states:
            db.add(ModuleState(module=m, difficulty=1))

    db.commit()
