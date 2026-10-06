"""Jednorazowy seed Banku B (chunki funkcyjne, spec dodatek v2 - Faza 2).

Stały zestaw ~20 fraz, niezależny od domeny i sesji - generowany raz, NIE
przez generator SourcePack (services/pack_gen.py). Uruchomienie:

    cd apps/api && .venv/Scripts/python.exe scripts/seed_function_chunks.py

--force nadpisuje istniejący Bank B (usuwa stare Chunk(bank='function') razem
z ich ChunkExposure) - używać świadomie, historia ekspozycji się kasuje.
"""

import argparse
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

CATEGORIES = [
    "starting_stance",
    "structuring",
    "example",
    "contrast_qualification",
    "repair_reformulation",
    "returning_to_thread",
    "buying_planning_time",
]
PER_CATEGORY = 4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="nadpisz istniejący Bank B")
    args = parser.parse_args()

    from app.db import db_session, init_db
    from app.models import Chunk, ChunkExposure
    from app.services import llm

    init_db()
    db = db_session()
    try:
        existing = db.query(Chunk).filter(Chunk.bank == "function").all()
        if existing and not args.force:
            print(f"Bank B ma już {len(existing)} chunków. Użyj --force, żeby nadpisać.")
            return
        if existing:
            ids = [c.id for c in existing]
            db.query(ChunkExposure).filter(ChunkExposure.chunk_id.in_(ids)).delete(
                synchronize_session=False
            )
            for c in existing:
                db.delete(c)
            db.commit()

        if not llm.llm_enabled():
            print("Brak klucza OPENAI_API_KEY - ustaw go (env albo ekran ustawień) i spróbuj ponownie.")
            return

        result = llm.complete_json(
            "generate_function_chunks",
            {"count_per_category": str(PER_CATEGORY)},
            llm.GeneratedFunctionChunks,
        )
        if result is None:
            print("LLM nie zwrócił poprawnego JSON-a.")
            return

        by_category: dict[str, int] = {}
        for c in result.chunks:
            if c.category not in CATEGORIES:
                print(f"Pomijam nieznaną kategorię: {c.category!r} ({c.text!r})")
                continue
            db.add(Chunk(bank="function", text=c.text, prompt_pl=c.prompt_pl, category=c.category))
            by_category[c.category] = by_category.get(c.category, 0) + 1

        missing = [cat for cat in CATEGORIES if by_category.get(cat, 0) == 0]
        if missing:
            print(f"UWAGA: brak fraz dla kategorii: {', '.join(missing)}")

        db.commit()
        total = sum(by_category.values())
        print(f"Zapisano {total} chunków Banku B: {by_category}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
