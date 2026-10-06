import json
import logging
from functools import lru_cache

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import KnownVocabulary, User

logger = logging.getLogger(__name__)

TOP_N_KNOWN_WORDS = 3000


@lru_cache
def language_config_file() -> dict:
    path = get_settings().language_config_path
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def language_config() -> dict:
    """fillers, repair_markers, progi pauz, prompt Whispera."""
    return language_config_file().get("config", {})


def structures() -> list[dict]:
    """Struktury gramatyczne do promptów generatora tekstów czytania.

    UWAGA: to jest wyłącznie lista opisowa (label/hint/example) do budowania
    promptów LLM dla trenera czytania - nie ma tu detekcji ani filtra jak w
    usuniętym module fluency. Trener czytania nie wymaga treningu płynności
    (czyta z kartki), więc splatanie struktur w tekst nie łamie warunków
    z Nation (spec §1b).
    """
    return language_config_file().get("structures", [])


def ensure_seeded(db: Session) -> None:
    if db.query(User).count() == 0:
        db.add(User(id=1))
        db.commit()

    if db.query(KnownVocabulary).count() > 0:
        return

    try:
        from wordfreq import top_n_list

        words = top_n_list("en", TOP_N_KNOWN_WORDS)
    except Exception:
        logger.warning("wordfreq niedostępny - KnownVocabulary startuje pusty")
        words = []

    for w in words:
        db.add(KnownVocabulary(lemma=w, source="top3000"))

    import_path = get_settings().known_vocabulary_import_path
    if import_path.exists():
        try:
            extra = json.loads(import_path.read_text(encoding="utf-8"))
            existing = set(words)
            for w in extra:
                if w not in existing:
                    db.add(KnownVocabulary(lemma=w, source="import"))
                    existing.add(w)
        except Exception:
            logger.exception("Import własnego słownictwa nie powiódł się (%s)", import_path)

    db.commit()
