"""Ustawienia instancji: baza ma pierwszeństwo, zmienna środowiskowa to fallback.

Dzięki temu ten sam kod obsługuje trzy scenariusze: desktop (użytkownik wpisuje
klucz w interfejsie), Docker lokalnie (klucz z .env) i hosting (sekret platformy
podany przy wdrożeniu, zmienialny później w ustawieniach).
"""

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import db_session
from ..models import AppSetting, now_iso

OPENAI_API_KEY = "openai_api_key"
PASSWORD_HASH = "password_hash"


def get_value(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    value = row.value if row else None
    return value or None


def set_value(db: Session, key: str, value: str | None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = now_iso()
    db.commit()


def _read(key: str) -> str | None:
    """Odczyt bez zewnętrznej sesji - wołane z miejsc, które jej nie mają."""
    db = db_session()
    try:
        return get_value(db, key)
    except Exception:
        return None
    finally:
        db.close()


def openai_api_key() -> str:
    """Klucz OpenAI: najpierw ustawienia w bazie, potem zmienna środowiskowa."""
    return _read(OPENAI_API_KEY) or get_settings().openai_api_key


def password_hash() -> str | None:
    return _read(PASSWORD_HASH)
