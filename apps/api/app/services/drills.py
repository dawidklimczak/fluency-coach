import json
from functools import lru_cache

from ..config import get_settings


@lru_cache
def load_drill_configs() -> dict[str, dict]:
    configs = {}
    for path in sorted(get_settings().drills_dir.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        configs[cfg["id"]] = cfg
    return configs


def get_drill_config(module: str) -> dict:
    configs = load_drill_configs()
    if module not in configs:
        raise KeyError(f"Brak konfiguracji drilla dla modułu: {module}")
    return configs[module]


def available_modules() -> list[dict]:
    return [
        {"id": c["id"], "name": c["name"], "attempts_per_session": c["attempts_per_session"]}
        for c in load_drill_configs().values()
    ]
