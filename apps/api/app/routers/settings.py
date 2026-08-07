"""Ustawienia instancji: klucz OpenAI i hasło. Chronione bramką z main.py."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..services import app_settings, auth

router = APIRouter(prefix="/api/settings", tags=["settings"])

MIN_PASSWORD_LEN = 8


def _mask(key: str) -> str:
    """Klucz nigdy nie wraca w jawnej postaci - tylko tyle, żeby go rozpoznać."""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 12 else "…"


class ApiKeyBody(BaseModel):
    api_key: str


class PasswordBody(BaseModel):
    current_password: str | None = None
    new_password: str


@router.get("")
def read_settings(db: Session = Depends(get_db)):
    key = app_settings.openai_api_key()
    from_env = bool(get_settings().openai_api_key) and not app_settings.get_value(
        db, app_settings.OPENAI_API_KEY
    )
    return {
        "openai_key_set": bool(key),
        "openai_key_hint": _mask(key) if key else None,
        "openai_key_from_env": from_env,
        "password_set": auth.password_configured(),
        "llm_model": get_settings().openai_llm_model,
    }


@router.put("/openai-key")
def set_openai_key(body: ApiKeyBody, db: Session = Depends(get_db)):
    key = body.api_key.strip()
    if not key:
        app_settings.set_value(db, app_settings.OPENAI_API_KEY, None)
        return {"ok": True, "openai_key_set": False}
    if not key.startswith("sk-"):
        raise HTTPException(422, "Klucz OpenAI zaczyna się od 'sk-'")

    # walidacja na żywo - bez tego użytkownik dowiedziałby się o błędzie
    # dopiero brakiem transkrypcji po nagraniu
    try:
        from openai import OpenAI

        OpenAI(api_key=key).models.list()
    except Exception:
        raise HTTPException(400, "OpenAI odrzuciło ten klucz")

    app_settings.set_value(db, app_settings.OPENAI_API_KEY, key)
    return {"ok": True, "openai_key_set": True, "openai_key_hint": _mask(key)}


@router.put("/password")
def set_password(body: PasswordBody, db: Session = Depends(get_db)):
    if len(body.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(422, f"Hasło musi mieć co najmniej {MIN_PASSWORD_LEN} znaków")
    # zmiana istniejącego hasła wymaga podania starego
    if auth.password_configured():
        if not body.current_password or not auth.check_password(body.current_password):
            raise HTTPException(403, "Nieprawidłowe obecne hasło")

    app_settings.set_value(
        db, app_settings.PASSWORD_HASH, auth.hash_password(body.new_password)
    )
    return {"ok": True}
