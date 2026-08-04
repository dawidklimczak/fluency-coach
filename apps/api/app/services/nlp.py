"""Wspólny, leniwie ładowany pipeline spaCy (en_core_web_sm).

Ładowanie modelu trwa ~1 s - trzymamy jedną instancję na proces.
Gdy modelu brak, funkcje zależne od spaCy zwracają None zamiast blokować
metryki czasowe (te nigdy nie zależą od NLP).
"""

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache
def get_nlp():
    try:
        import spacy

        return spacy.load("en_core_web_sm")
    except Exception:
        logger.warning(
            "spaCy en_core_web_sm niedostępny - metryki językowe składniowe wyłączone"
        )
        return None


def nlp_available() -> bool:
    return get_nlp() is not None
