"""Generowanie zadań przez LLM na żądanie; logika w services/task_gen.py."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import llm, task_gen
from ..services.drills import load_drill_configs

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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
    if not task_gen.generation_supported(body.module):
        raise HTTPException(422, f"Generowanie nie jest wspierane dla: {body.module}")
    if task_gen.structure_instruction(body.target_structure) is None:
        raise HTTPException(404, f"Nieznana struktura: {body.target_structure}")

    created = task_gen.generate_tasks(
        db, body.module, body.difficulty, body.count, body.target_structure
    )
    if not created:
        raise HTTPException(502, "LLM nie zwrócił poprawnych zadań")
    return {"created": len(created), "task_ids": created}


@router.get("/stock")
def stock(db: Session = Depends(get_db)):
    """Zapas ŻYWYCH zadań (poniżej limitu 3 pojawień) per moduł i trudność."""
    return task_gen.usable_stock(db)
