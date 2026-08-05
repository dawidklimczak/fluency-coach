"""LLM przez OpenAI (spec sekcja 8; decyzja: jeden klucz OpenAI zamiast Anthropic).

LLM robi trzy rzeczy i nic więcej: generuje zadania offline, ocenia jakościowo
wybrane moduły po próbie i buduje obserwacje tygodniowe. Nigdy nie ocenia
płynności - płynność jest mierzona, nie oceniana.

Każdy prompt zwraca wyłącznie JSON walidowany Pydantic. Jeden retry przy
błędzie parsowania, potem None - brak oceny nigdy nie blokuje metryk.
"""

import json
import logging
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

T = TypeVar("T", bound=BaseModel)


def llm_enabled() -> bool:
    return bool(get_settings().openai_api_key)


def load_prompt(name: str, variables: dict[str, str]) -> str:
    """Prompty w app/prompts/*.md (spec sekcja 8), tokeny {{nazwa}}."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def complete_json(prompt_name: str, variables: dict[str, str], schema: type[T]) -> T | None:
    if not llm_enabled():
        return None
    try:
        from openai import OpenAI

        settings = get_settings()
        client = OpenAI(api_key=settings.openai_api_key)
        prompt = load_prompt(prompt_name, variables)

        for attempt in range(2):  # jeden retry (spec sekcja 8)
            response = client.chat.completions.create(
                model=settings.openai_llm_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2 if attempt == 0 else 0.0,
            )
            raw = response.choices[0].message.content or ""
            try:
                return schema.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError):
                logger.warning(
                    "Niepoprawny JSON z LLM (%s, próba %d)", prompt_name, attempt + 1
                )
        return None
    except Exception:
        logger.exception("Wywołanie LLM nie powiodło się (%s)", prompt_name)
        return None


# --- schematy odpowiedzi ----------------------------------------------------


class ParaphraseEval(BaseModel):
    meaning_preserved: bool
    comment: str = ""


class SimplifyEval(BaseModel):
    meaning_preserved: bool
    simpler: bool
    comment: str = ""


class DescribeEval(BaseModel):
    guess: str
    guessable: bool


class IdeaExpansionEval(BaseModel):
    coherent: bool
    comment: str = ""


class GeneratedTask(BaseModel):
    prompt_text: str
    target_structure: str | None = None
    payload: dict | None = None
    tags: list[str] = []


class GeneratedTasks(BaseModel):
    tasks: list[GeneratedTask]


class ObservationItem(BaseModel):
    pattern: str
    example: str | None = None
    note: str | None = None


class ObservationsResult(BaseModel):
    items: list[ObservationItem]


class GrammarNote(BaseModel):
    pattern: str
    example: str | None = None
    note: str | None = None


class SessionFeedback(BaseModel):
    comment: str
    went_well: list[str] = []
    to_improve: list[str] = []
    grammar: list[GrammarNote] = []


# --- ocena jakościowa po próbie (spec 8 pkt 2) ------------------------------


def evaluate_attempt(module: str, task_prompt: str, payload: dict | None, transcript: str) -> dict | None:
    """Ocena jakościowa dla modułów z llm_eval=true. Zwraca dict do attempt.llm_eval."""
    payload = payload or {}
    if module == "paraphrase":
        result = complete_json(
            "eval_paraphrase",
            {"source": str(payload.get("source", task_prompt)), "transcript": transcript},
            ParaphraseEval,
        )
    elif module == "simplify":
        result = complete_json(
            "eval_simplify",
            {"source": str(payload.get("source", task_prompt)), "transcript": transcript},
            SimplifyEval,
        )
    elif module == "describe_without_word":
        target = str((payload.get("forbidden_words") or [""])[0])
        result = complete_json(
            "eval_describe",
            {"target": target, "transcript": transcript},
            DescribeEval,
        )
        if result is not None:
            out = result.model_dump()
            out["matches_target"] = (
                result.guess.strip().lower() == target.strip().lower()
            )
            return out
    elif module == "idea_expansion":
        result = complete_json(
            "eval_idea_expansion",
            {"seed": str(payload.get("seed", task_prompt)), "transcript": transcript},
            IdeaExpansionEval,
        )
    else:
        return None
    return result.model_dump() if result is not None else None
