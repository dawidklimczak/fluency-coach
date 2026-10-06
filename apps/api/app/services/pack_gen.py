"""Generator SourcePack (spec §7): wejście PersonalContext + Domain +
KnownVocabulary + chunki z poprzednich 3 sesji tej domeny.

Walidacja przed zapisem - odrzuć i regeneruj przy niepowodzeniu:
  - każde słowo treściowe w seed_text należy do KnownVocabulary
  - transfer_prompt nie wymaga przypomnienia sobie faktu z życia użytkownika
  - przy support_ceiling >= 2 task_type to narrative albo description

Bank B (chunki funkcyjne) NIE jest generowany tu - to jednorazowy skrypt,
patrz scripts/seed_function_chunks.py (decyzja: stały zestaw, nie per-sesja).
"""

import logging
import re
from functools import lru_cache

from sqlalchemy.orm import Session

from ..models import Chunk, PersonalContext, SourcePack
from . import llm
from .nlp import get_nlp

logger = logging.getLogger(__name__)

MAX_GENERATION_ATTEMPTS = 5
NARRATIVE_TASK_TYPES = {"narrative", "description"}
MIN_SUPPORT_FOR_NARRATIVE_ONLY = 2
RECENT_PACKS_FOR_REPEAT_CHUNKS = 3

# słowa dopuszczone bez sprawdzania (interpunkcja doklejona do tokenu jest
# usuwana przed porównaniem, więc to naprawdę tylko pojedyncze litery/cyfry)
_ALWAYS_ALLOWED_POS = {"PROPN", "NUM", "X"}


def _tokenize_content_words(text: str) -> list[tuple[str, str | None]]:
    """Zwraca [(lemma_lower, pos)] dla tokenów alfabetycznych. Bez spaCy: pos=None."""
    nlp = get_nlp()
    if nlp is None:
        tokens = re.findall(r"[a-zA-Z']+", text.lower())
        return [(t, None) for t in tokens]
    doc = nlp(text)
    return [(t.lemma_.lower(), t.pos_) for t in doc if t.is_alpha]


def unknown_words(text: str, known_lemmas: set[str]) -> list[str]:
    """Słowa spoza KnownVocabulary (poza rzeczownikami własnymi/liczbami)."""
    seen = []
    for lemma, pos in _tokenize_content_words(text):
        if pos in _ALWAYS_ALLOWED_POS:
            continue
        if lemma in known_lemmas:
            continue
        seen.append(lemma)
    return sorted(set(seen))


def validate_generated_pack(
    pack: llm.GeneratedSourcePack,
    known_lemmas: set[str],
    support_ceiling: int,
) -> list[str]:
    """Zwraca listę powodów odrzucenia; pusta lista = pack przechodzi walidację."""
    reasons: list[str] = []

    unknown = unknown_words(pack.seed_text, known_lemmas)
    if unknown:
        reasons.append(f"nieznane słowa w seed_text: {', '.join(unknown[:10])}")

    if pack.requires_personal_recall:
        reasons.append("transfer_prompt wymaga przypomnienia sobie faktu z życia")

    if support_ceiling >= MIN_SUPPORT_FOR_NARRATIVE_ONLY:
        if pack.task_type not in NARRATIVE_TASK_TYPES:
            reasons.append(
                f"task_type={pack.task_type!r} niedozwolony przy "
                f"support_ceiling>={MIN_SUPPORT_FOR_NARRATIVE_ONLY} "
                f"(dozwolone: {sorted(NARRATIVE_TASK_TYPES)})"
            )

    if not pack.chunks:
        reasons.append("brak chunks")
    if any(not c.prompt_pl.strip() for c in pack.chunks):
        reasons.append("chunk bez prompt_pl")
    if not pack.guiding_questions:
        reasons.append("brak guiding_questions")

    return reasons


def known_lemma_set(db: Session) -> set[str]:
    """Lemmy KnownVocabulary - budowane raz per wywołanie (spaCy lemmatyzacja
    3000 wpisów zajmuje ok. 1-2 s, nie ma sensu cache'ować między próbami
    generacji, bo słownictwo rzadko się zmienia w trakcie jednej sesji).

    Zawiera zarówno lemmę, jak i surową formę każdego słowa: lemmatyzacja
    pojedynczego słowa bez kontekstu zdania jest niewiarygodna dla wyrazów,
    których lemma zależy od roli składniowej (np. spaCy lemmatyzuje "her" jako
    dopełnienie na "she", ale jako zaimek dzierżawczy zostawia "her" - bez
    zdania nie da się tego rozstrzygnąć). Dodanie surowej formy jako fallback
    zapobiega fałszywym odrzuceniom typu "her" nieznane."""
    from ..models import KnownVocabulary

    words = [row[0] for row in db.query(KnownVocabulary.lemma).all()]
    known: set[str] = {w.lower() for w in words}
    nlp = get_nlp()
    if nlp is None:
        return known
    for doc in nlp.pipe(words):
        for tok in doc:
            if tok.is_alpha:
                known.add(tok.lemma_.lower())
    return known


def _active_personal_context(db: Session) -> str:
    ctx = (
        db.query(PersonalContext)
        .filter(PersonalContext.active.is_(True))
        .order_by(PersonalContext.version.desc())
        .first()
    )
    return ctx.content if ctx else ""


def _repeat_chunk_texts(db: Session, domain_id: int) -> list[str]:
    recent_pack_ids = [
        row[0]
        for row in db.query(SourcePack.id)
        .filter(SourcePack.domain_id == domain_id, SourcePack.status == "validated")
        .order_by(SourcePack.created_at.desc())
        .limit(RECENT_PACKS_FOR_REPEAT_CHUNKS)
        .all()
    ]
    if not recent_pack_ids:
        return []
    return [
        row[0]
        for row in db.query(Chunk.text)
        .filter(Chunk.bank == "domain", Chunk.source_pack_id.in_(recent_pack_ids))
        .all()
    ]


def _task_type_constraint(support_ceiling: int) -> str:
    if support_ceiling >= MIN_SUPPORT_FOR_NARRATIVE_ONLY:
        return (
            "Task type constraint: at this support level the task MUST be a "
            "narrative or a description - never argumentative. Argumentative "
            "tasks demand more reasoning and add load the learner isn't ready "
            "for yet at this support level."
        )
    return "Task type constraint: none - narrative, description, or argumentative are all fine."


def generate_source_pack(
    db: Session, domain, support_ceiling: int
) -> SourcePack | None:
    """Generuje, waliduje i zapisuje SourcePack + Chunk(bank='domain').

    Do MAX_GENERATION_ATTEMPTS prób; przy niepowodzeniu wszystkich zwraca None
    i loguje ostatnie powody odrzucenia (żaden nieważny pack nie trafia do bazy).
    """
    if not llm.llm_enabled():
        return None

    known_lemmas = known_lemma_set(db)
    personal_context = _active_personal_context(db)
    repeat_chunks = _repeat_chunk_texts(db, domain.id)

    last_reasons: list[str] = []
    seen_unknown_words: set[str] = set()
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        avoid_words = (
            f"Words to avoid (too rare/technical - use simpler everyday alternatives): "
            f"{', '.join(sorted(seen_unknown_words))}"
            if seen_unknown_words
            else ""
        )
        result = llm.complete_json(
            "generate_source_pack",
            {
                "personal_context": personal_context or "(brak zapisanego kontekstu)",
                "domain": domain.name,
                "task_type_constraint": _task_type_constraint(support_ceiling),
                "repeat_chunks": "\n".join(f"- {c}" for c in repeat_chunks) or "(brak - pierwsza sesja w tej domenie)",
                "avoid_words": avoid_words,
            },
            llm.GeneratedSourcePack,
        )
        if result is None:
            last_reasons = ["LLM nie zwrócił poprawnego JSON-a"]
            continue

        last_reasons = validate_generated_pack(result, known_lemmas, support_ceiling)
        if last_reasons:
            seen_unknown_words |= set(unknown_words(result.seed_text, known_lemmas))
            logger.warning(
                "SourcePack odrzucony (próba %d/%d): %s",
                attempt + 1, MAX_GENERATION_ATTEMPTS, "; ".join(last_reasons),
            )
            continue

        pack = SourcePack(
            domain_id=domain.id,
            seed_text=result.seed_text,
            guiding_questions=result.guiding_questions,
            keywords=result.keywords,
            transfer_prompt=result.transfer_prompt,
            status="validated",
        )
        db.add(pack)
        db.flush()  # potrzebne id do FK w Chunk
        for c in result.chunks:
            db.add(Chunk(bank="domain", text=c.text, prompt_pl=c.prompt_pl, source_pack_id=pack.id))
        db.commit()
        return pack

    logger.error(
        "Generacja SourcePack nie powiodła się po %d próbach: %s",
        MAX_GENERATION_ATTEMPTS, "; ".join(last_reasons),
    )
    return None
