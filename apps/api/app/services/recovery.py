"""Recovery Drill (spec zmian §8): trening odzyskiwania kontroli nad wypowiedzią
po zgubieniu wątku - nie jest testem językowym, treść nigdy nie jest oceniana,
tylko metryki czasowe jak w każdej innej Attempt.
"""

from sqlalchemy.orm import Session

from ..models import Chunk
from . import llm

KIND_ORDER = ["lost_thread", "reformulation", "clarification_followup"]
SPEAK_LIMIT_S = 30

_PROMPTS = {
    "lost_thread": "Imagine you lost your thread. Get back to the main point and continue for 20-30 seconds.",
    "reformulation": "Interrupt yourself, rephrase what you were saying, and continue.",
}
# kategorie z Banku B najbardziej pasujące do każdego kroku (spec zmian §5.1/§8.1)
_SUGGESTED_CATEGORY = {
    "lost_thread": "returning_to_thread",
    "reformulation": "repair_reformulation",
}


def _suggested_chunk_text(db: Session, kind: str) -> str | None:
    category = _SUGGESTED_CATEGORY.get(kind)
    if category is None:
        return None
    chunk = (
        db.query(Chunk)
        .filter(Chunk.bank == "function", Chunk.category == category)
        .order_by(Chunk.id)
        .first()
    )
    return chunk.text if chunk else None


def static_trial(db: Session, kind: str) -> dict:
    """lost_thread i reformulation nie potrzebują LLM - prompt jest statyczny."""
    return {
        "kind": kind,
        "prompt": _PROMPTS[kind],
        "suggested_chunk": _suggested_chunk_text(db, kind),
        "speaking_limit_seconds": SPEAK_LIMIT_S,
    }


def generate_follow_up(transcript: str | None) -> str | None:
    """clarification_followup (spec zmian §8.1, §10.6): jedno pytanie na bazie
    transkrypcji poprzedniej próby, best-effort - None gdy LLM wyłączony/brak
    transkrypcji, wtedy frontend pokazuje statyczne pytanie zapasowe."""
    if not transcript or not llm.llm_enabled():
        return None
    result = llm.complete_json("recovery_followup", {"transcript": transcript}, llm.GeneratedFollowUp)
    return result.question if result else None


FALLBACK_FOLLOW_UP = "Could you give me an example?"
