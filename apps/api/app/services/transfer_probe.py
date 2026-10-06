"""Klasyfikacja wyniku sondy transferowej (spec §3, dodatek v2B) oraz
generowanie pytania "far transfer" (spec zmian §6.2).

answered i redirected są równoważne - obie liczą się jako sukces. Tylko
stalled jest sygnałem negatywnym. phonation_time_ratio < 0.5 jest twardym
sygnałem stalled bez pytania LLM (transkrypcja może być pusta/None).
"""

from sqlalchemy.orm import Session

from . import llm
from .pack_gen import _active_personal_context

STALL_PHONATION_THRESHOLD = 0.5
VALID_OUTCOMES = {"answered", "redirected", "stalled"}


def classify_outcome(
    question: str, transcript: str | None, phonation_time_ratio: float | None
) -> str:
    if phonation_time_ratio is not None and phonation_time_ratio < STALL_PHONATION_THRESHOLD:
        return "stalled"
    if not transcript or not llm.llm_enabled():
        # brak transkrypcji/LLM nie może fałszywie oznaczyć jako stalled -
        # fail open na "answered", bo phonation już wykluczył realny zamiek
        return "answered"
    result = llm.complete_json(
        "classify_transfer_outcome",
        {"question": question, "transcript": transcript},
        llm.TransferProbeOutcome,
    )
    if result is not None and result.outcome in VALID_OUTCOMES:
        return result.outcome
    return "answered"


def generate_far_transfer_prompt(db: Session) -> str | None:
    """Pytanie 'far' - świadomie nie bierze Domain/SourcePack jako wejścia
    (spec zmian §10.4). Best-effort: None jeśli LLM wyłączony/zawiedzie, sesja
    startuje mimo to i frontend pomija krok Far Transfer."""
    if not llm.llm_enabled():
        return None
    result = llm.complete_json(
        "far_transfer",
        {"personal_context": _active_personal_context(db) or "(brak zapisanego kontekstu)"},
        llm.GeneratedFarTransferPrompt,
    )
    return result.prompt if result else None
