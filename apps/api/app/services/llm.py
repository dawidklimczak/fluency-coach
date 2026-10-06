"""LLM przez OpenAI (decyzja: jeden klucz OpenAI zamiast Anthropic).

Każdy prompt zwraca wyłącznie JSON walidowany Pydantic. Jeden retry przy
błędzie parsowania, potem None - brak wyniku LLM nigdy nie blokuje metryk.
Nigdy nie ocenia płynności - płynność jest mierzona, nie oceniana.
"""

import json
import logging
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .app_settings import openai_api_key

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

T = TypeVar("T", bound=BaseModel)


def llm_enabled() -> bool:
    return bool(openai_api_key())


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
        client = OpenAI(api_key=openai_api_key())
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


class GeneratedReadingText(BaseModel):
    title: str
    text: str


class TransferProbeOutcome(BaseModel):
    """Klasyfikacja post-hoc sondy transferowej (spec dodatek v2B).

    answered i redirected są równoważne - obie liczą się jako sukces w
    baseline'ie i regułach wsparcia. Tylko stalled jest sygnałem negatywnym.
    """

    outcome: str  # 'answered' | 'redirected' | 'stalled'


class GeneratedChunk(BaseModel):
    text: str
    # opis sytuacji po polsku do Trybu A chunk drillu (dodatek v2)
    prompt_pl: str


class GeneratedSourcePack(BaseModel):
    """Wyjście generatora SourcePack (spec §7)."""

    seed_text: str
    guiding_questions: list[str]
    keywords: list[str]
    chunks: list[GeneratedChunk]
    transfer_prompt: str
    task_type: str  # 'narrative' | 'description' | 'argumentative'
    # self-ocena LLM - czy transfer_prompt wymaga przypomnienia sobie
    # konkretnego faktu z życia użytkownika spoza tego, co dostał w packu
    requires_personal_recall: bool


class GeneratedFunctionChunk(BaseModel):
    text: str
    prompt_pl: str
    category: str


class GeneratedFunctionChunks(BaseModel):
    chunks: list[GeneratedFunctionChunk]


class GeneratedFarTransferPrompt(BaseModel):
    """Sonda 'far' (spec zmian §6.2, §10.4): świadomie NIE zależy od aktywnej
    Domain - mierzy generalizację automatyzmu poza wytrenowanym tematem."""

    prompt: str


class GeneratedDiagnosticPromptSet(BaseModel):
    """Bottleneck Diagnostic (spec zmian §2.2, §10.1) - matched prompt set:
    ten sam poziom trudności/abstrakcji, różne konkretne pytania dla A/B/C,
    plus analogiczne pytanie po polsku dla opcjonalnej kontroli."""

    cold: str
    supplied_ideas_prompt: str
    supplied_ideas: list[str]  # dokładnie 3 krótkie kierunki (bez gotowych zdań)
    self_plan: str
    native_control: str


class GeneratedFollowUp(BaseModel):
    """Recovery Drill (spec zmian §8.1, §10.6): dokładnie jedno pytanie
    dopytujące, świadomie bez pola na feedback - schemat fizycznie
    uniemożliwia zwrócenie czegokolwiek poza pytaniem."""

    question: str
