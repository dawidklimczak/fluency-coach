"""Buduje startowy bank zadań Grammar: data/grammar_seed_items.json.

Jedno żądanie LLM na umiejętność z data/grammar_skills.json. Plik trafia do
repo, dzięki czemu pierwsza runda po instalacji nie czeka na generowanie.
Uruchomienie (z katalogu apps/api, wymaga klucza OpenAI w ustawieniach lub .env):

    .venv/Scripts/python.exe scripts/build_seed_bank.py [--only id1,id2] [--workers 4]

Istniejące zadania w pliku zostają; skrypt dogenerowuje tylko brakujące
umiejętności (albo te z --only).
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services import grammar, skills  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    path = get_settings().grammar_seed_items_path
    items = json.loads(path.read_text(encoding="utf-8"))["items"] if path.exists() else []
    only = {s for s in args.only.split(",") if s}
    have = {i["skill_id"] for i in items}
    todo = [s for s in skills.all_skills() if (s["id"] in only if only else s["id"] not in have)]
    if only:
        items = [i for i in items if i["skill_id"] not in only]
    print(f"{len(todo)} umiejętności do wygenerowania")

    def work(sdef: dict) -> tuple[str, list[dict]]:
        got = grammar.request_items(sdef, grammar.DEFAULT_CONTEXT, [])
        return sdef["id"], [{"skill_id": sdef["id"], **it.model_dump()} for it in got]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for sid, got in pool.map(work, todo):
            print(f"  {sid}: {len(got)}")
            items.extend(got)
            # zapis po każdej umiejętności - przerwanie nie traci już zrobionych
            order = {s["id"]: n for n, s in enumerate(skills.all_skills())}
            items.sort(key=lambda i: order.get(i["skill_id"], 999))
            path.write_text(
                json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
    print(f"Razem {len(items)} zadań -> {path}")


if __name__ == "__main__":
    main()
