"""Generowanie zadań przez LLM (spec 8 pkt 1) i automat uzupełniania puli.

Automat rusza w tle po zamknięciu sesji nauki: dla używanych modułów sprawdza
zapas ŻYWYCH zadań (poniżej MAX_TASK_USES pojawień) na aktualnym poziomie
trudności +/-1 i dogenerowuje do progu. Nigdy w trakcie treningu.
"""

import logging
import uuid

from sqlalchemy.orm import Session

from ..db import db_session
from ..models import Task
from . import adaptation, llm
from .seed import structures as seed_structures
from .task_select import exhausted_task_ids

logger = logging.getLogger(__name__)

STOCK_THRESHOLD = 20  # spec sekcja 8: dogeneruj, gdy zapas spadnie poniżej 20
MAX_GENERATE_PER_CALL = 30

MODULE_DESCRIPTIONS = {
    "rapid_response": "The user answers a short concrete question immediately, 5-15 seconds. Prompts are direct questions.",
    "unexpected_questions": "Odd, unexpected but answerable questions that force an immediate start. 15 seconds.",
    "fluency_sprint": "A simple topic card the user talks about for 120 seconds without stopping. Prompts name a broad everyday topic.",
    "describe_without_word": "Taboo-style: the user describes a concept without using the word itself, its inflections or close synonyms. 30 seconds.",
    "paraphrase": "The user says the same sentence three different ways. The prompt gives one natural everyday sentence to paraphrase.",
    "simplify": "The prompt is a deliberately overcomplicated, formal sentence; the user restates it simply. 20 seconds.",
    "idea_expansion": "The prompt is a short bare statement; the user expands it into about five connected sentences. 45 seconds.",
    "story_loop": "A personal narrative topic told three times with shrinking time limits (90/60/45 s). Prompts ask for a story from the user's life.",
}

PAYLOAD_INSTRUCTIONS = {
    "describe_without_word": (
        'Each task must include payload {"forbidden_words": [target word, 2-4 inflections and close synonyms]}. '
        "prompt_text is: Describe: <target word>."
    ),
    "paraphrase": 'Each task must include payload {"source": "<the sentence>"} and prompt_text "Say this three different ways: <the sentence>".',
    "simplify": 'Each task must include payload {"source": "<the sentence>"} and prompt_text "Simplify: <the sentence>".',
    "idea_expansion": 'Each task must include payload {"seed": "<the statement>", "target_sentences": 5} and prompt_text "Expand into five sentences: <the statement>".',
    "story_loop": 'Each task must include payload {"round_limits_s": [90, 60, 45]}.',
}

ID_PREFIX = {
    "rapid_response": "rr",
    "unexpected_questions": "uq",
    "fluency_sprint": "fs",
    "describe_without_word": "dw",
    "paraphrase": "pp",
    "simplify": "sp",
    "idea_expansion": "ie",
    "story_loop": "sl",
}


def generation_supported(module: str) -> bool:
    return module in MODULE_DESCRIPTIONS


def structure_instruction(structure_id: str | None) -> str | None:
    """Opis struktury do promptu; None gdy struktura nieznana."""
    if not structure_id:
        return ""
    s = next((x for x in seed_structures() if x["id"] == structure_id), None)
    if s is None:
        return None
    return (
        f"Target grammar structure: {s['label']} ({s.get('hint', '')}). "
        f"Example of the structure in use: {s.get('example', '')}"
    )


def generate_tasks(
    db: Session,
    module: str,
    difficulty: int,
    count: int,
    target_structure: str | None = None,
) -> list[str]:
    """Generuje i zapisuje zadania; zwraca listę id (pusta przy niepowodzeniu)."""
    count = max(1, min(count, MAX_GENERATE_PER_CALL))
    instruction = structure_instruction(target_structure)
    if instruction is None:
        return []
    result = llm.complete_json(
        "generate_tasks",
        {
            "module": module,
            "module_description": MODULE_DESCRIPTIONS[module],
            "difficulty": str(difficulty),
            "count": str(count),
            "structure_instruction": instruction,
            "payload_instruction": PAYLOAD_INSTRUCTIONS.get(module, ""),
        },
        llm.GeneratedTasks,
    )
    if result is None:
        return []

    created = []
    for t in result.tasks[:count]:
        task_id = f"{ID_PREFIX[module]}_llm_{uuid.uuid4().hex[:8]}"
        db.add(
            Task(
                id=task_id,
                module=module,
                difficulty=difficulty,
                target_structure=target_structure or t.target_structure,
                structure_mode=None,
                prompt_text=t.prompt_text,
                payload=t.payload,
                tags=t.tags or None,
                source="llm",
            )
        )
        created.append(task_id)
    db.commit()
    return created


def usable_stock(db: Session) -> dict[str, dict[int, int]]:
    """Zapas żywych zadań (poniżej limitu pojawień) per moduł i trudność."""
    exhausted = exhausted_task_ids(db)
    out: dict[str, dict[int, int]] = {}
    for task_id, module, difficulty in db.query(
        Task.id, Task.module, Task.difficulty
    ).all():
        if task_id in exhausted:
            continue
        out.setdefault(module, {}).setdefault(difficulty, 0)
        out[module][difficulty] += 1
    return out


def top_up_modules(modules: list[str]) -> None:
    """Uzupełnia pulę w tle (BackgroundTasks po zamknięciu sesji nauki)."""
    if not llm.llm_enabled():
        return
    db = db_session()
    try:
        stock = usable_stock(db)
        for module in modules:
            if not generation_supported(module):
                continue
            level = adaptation.get_difficulty(db, module)
            for difficulty in sorted({max(1, level - 1), level, min(10, level + 1)}):
                have = stock.get(module, {}).get(difficulty, 0)
                if have >= STOCK_THRESHOLD:
                    continue
                created = generate_tasks(
                    db, module, difficulty, STOCK_THRESHOLD - have
                )
                if created:
                    logger.info(
                        "Dogenerowano %d zadań: %s, trudność %d",
                        len(created), module, difficulty,
                    )
    except Exception:
        logger.exception("Automat uzupełniania puli zadań nie powiódł się")
    finally:
        db.close()
