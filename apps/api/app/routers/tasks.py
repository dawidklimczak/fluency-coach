"""Generowanie zadań przez LLM (spec 8 pkt 1) - poza sesją, na żądanie."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Task
from ..services import llm
from ..services.drills import load_drill_configs
from ..services.seed import structures as seed_structures

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

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
    "story_loop": 'Each task must include payload {"round_limits_s": [90, 60, 45]} and mention "Round 1: 90 seconds." at the end of prompt_text.',
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


class GenerateBody(BaseModel):
    module: str
    difficulty: int = Field(ge=1, le=10)
    count: int = Field(default=10, ge=1, le=30)
    target_structure: str | None = None


@router.post("/generate")
def generate(body: GenerateBody, db: Session = Depends(get_db)):
    if not llm.llm_enabled():
        raise HTTPException(503, "Brak klucza OPENAI_API_KEY")
    if body.module not in load_drill_configs():
        raise HTTPException(404, f"Nieznany moduł: {body.module}")
    if body.module not in MODULE_DESCRIPTIONS:
        raise HTTPException(422, f"Generowanie nie jest wspierane dla: {body.module}")

    structure_instruction = ""
    if body.target_structure:
        s = next(
            (x for x in seed_structures() if x["id"] == body.target_structure), None
        )
        if s is None:
            raise HTTPException(404, f"Nieznana struktura: {body.target_structure}")
        structure_instruction = (
            f"Target grammar structure: {s['label']} ({s.get('hint', '')}). "
            f"Example of the structure in use: {s.get('example', '')}"
        )

    result = llm.complete_json(
        "generate_tasks",
        {
            "module": body.module,
            "module_description": MODULE_DESCRIPTIONS[body.module],
            "difficulty": str(body.difficulty),
            "count": str(body.count),
            "structure_instruction": structure_instruction,
            "payload_instruction": PAYLOAD_INSTRUCTIONS.get(body.module, ""),
        },
        llm.GeneratedTasks,
    )
    if result is None:
        raise HTTPException(502, "LLM nie zwrócił poprawnych zadań")

    created = []
    for t in result.tasks[: body.count]:
        task_id = f"{ID_PREFIX[body.module]}_llm_{uuid.uuid4().hex[:8]}"
        db.add(
            Task(
                id=task_id,
                module=body.module,
                difficulty=body.difficulty,
                target_structure=body.target_structure or t.target_structure,
                structure_mode=None,
                prompt_text=t.prompt_text,
                payload=t.payload,
                tags=t.tags or None,
                source="llm",
            )
        )
        created.append(task_id)
    db.commit()
    return {"created": len(created), "task_ids": created}


@router.get("/stock")
def stock(db: Session = Depends(get_db)):
    """Zapas zadań per moduł i trudność - do decyzji o dogenerowaniu (spec 8: próg 20)."""
    rows = db.query(Task.module, Task.difficulty).all()
    out: dict[str, dict[int, int]] = {}
    for module, difficulty in rows:
        out.setdefault(module, {}).setdefault(difficulty, 0)
        out[module][difficulty] += 1
    return out
