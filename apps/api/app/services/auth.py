"""Uwierzytelnianie: jedno hasło na instancję (aplikacja jest jednoosobowa).

Zasada fail closed: żądanie spoza localhost przy nieustawionym haśle jest
odrzucane. Uruchomienie lokalne (desktop, Docker na localhost) nie wymaga
hasła i o nie nie pyta - dzięki temu ten sam kod obsługuje oba scenariusze.

Hasło można podać zmienną APP_PASSWORD (przy wdrożeniu, zanim usługa wstanie)
albo ustawić w interfejsie; wartość z bazy ma pierwszeństwo.
"""

import hashlib
import hmac
import secrets
import time

from ..config import get_settings
from . import app_settings

COOKIE_NAME = "sat_session"
SESSION_TTL_S = 60 * 60 * 24 * 30  # 30 dni - logowanie raz na urządzenie

# "testclient" to host używany przez fastapi.testclient; traktujemy go jak
# lokalny, żeby testy nie musiały się logować.
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=32,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def check_password(password: str) -> bool:
    """Sprawdza wobec hasła z bazy (hash), a gdy go nie ma - wobec APP_PASSWORD."""
    stored = app_settings.password_hash()
    if stored:
        return verify_password(password, stored)
    env_password = get_settings().app_password
    if env_password:
        return hmac.compare_digest(password, env_password)
    return False


def password_configured() -> bool:
    return bool(app_settings.password_hash() or get_settings().app_password)


def is_local_client(host: str | None) -> bool:
    return (host or "") in LOCAL_HOSTS


# --- token sesji (HMAC, bez zewnętrznych zależności) ------------------------


def _signing_key() -> bytes:
    """Klucz podpisujący; generowany przy pierwszym uruchomieniu i zapamiętany.

    Zmiana pliku unieważnia wszystkie sesje - to zamierzone.
    """
    path = get_settings().instance_key_path
    if path.exists():
        return bytes.fromhex(path.read_text(encoding="utf-8").strip())
    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.hex(), encoding="utf-8")
    return key


def issue_token(now: float | None = None) -> str:
    issued_at = int(now if now is not None else time.time())
    signature = hmac.new(
        _signing_key(), str(issued_at).encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{issued_at}.{signature}"


def verify_token(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    issued_str, signature = token.rsplit(".", 1)
    try:
        issued_at = int(issued_str)
    except ValueError:
        return False
    expected = hmac.new(
        _signing_key(), issued_str.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    current = now if now is not None else time.time()
    return 0 <= current - issued_at <= SESSION_TTL_S


def request_authorized(client_host: str | None, token: str | None) -> bool:
    """Czy żądanie może być obsłużone.

    Lokalnie bez hasła - tak. Lokalnie z ustawionym hasłem - wymagamy tokenu,
    bo skoro ktoś je ustawił, to znaczy, że chce ochrony także na tej maszynie.
    """
    if not password_configured():
        return is_local_client(client_host)
    return verify_token(token)
