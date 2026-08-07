"""Bramka: hasło instancji, fail closed, hashowanie i token sesji."""

import time

import pytest

from app.services import auth


def test_password_hash_roundtrip():
    stored = auth.hash_password("correct horse battery")
    assert auth.verify_password("correct horse battery", stored)
    assert not auth.verify_password("wrong", stored)


def test_verify_password_rejects_garbage():
    assert not auth.verify_password("x", "not-a-hash")
    assert not auth.verify_password("x", "md5$aa$bb")


def test_token_roundtrip_and_expiry():
    token = auth.issue_token()
    assert auth.verify_token(token)
    # token starszy niż TTL przestaje być ważny
    old = auth.issue_token(now=time.time() - auth.SESSION_TTL_S - 10)
    assert not auth.verify_token(old)


def test_token_rejects_tampering():
    token = auth.issue_token()
    issued, signature = token.rsplit(".", 1)
    assert not auth.verify_token(f"{int(issued) + 1}.{signature}")
    assert not auth.verify_token("garbage")
    assert not auth.verify_token(None)


def test_local_client_detection():
    assert auth.is_local_client("127.0.0.1")
    assert auth.is_local_client("::1")
    assert not auth.is_local_client("203.0.113.7")
    assert not auth.is_local_client(None)


def test_authorization_without_password_is_local_only(monkeypatch):
    monkeypatch.setattr(auth, "password_configured", lambda: False)
    assert auth.request_authorized("127.0.0.1", None)
    assert not auth.request_authorized("203.0.113.7", None)


def test_authorization_with_password_requires_token(monkeypatch):
    monkeypatch.setattr(auth, "password_configured", lambda: True)
    assert not auth.request_authorized("127.0.0.1", None)
    assert auth.request_authorized("203.0.113.7", auth.issue_token())


@pytest.mark.parametrize("host", ["203.0.113.7", "10.0.0.5"])
def test_remote_request_blocked_without_password(host, monkeypatch):
    """Fail closed: publiczny interfejs bez hasła nie obsługuje niczego."""
    monkeypatch.setattr(auth, "password_configured", lambda: False)
    assert not auth.request_authorized(host, auth.issue_token())


# --- middleware end-to-end -------------------------------------------------


def _client(host: str = "testclient"):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, client=(host, 50000))


def test_remote_without_password_gets_503_everywhere():
    """Cała instancja odmawia obsługi, także strony - nie tylko API."""
    with _client("203.0.113.7") as c:
        assert c.get("/api/health").status_code == 503
        assert c.get("/api/sessions/modules").status_code == 503
        assert c.get("/").status_code == 503


def test_remote_with_password_requires_login(monkeypatch):
    monkeypatch.setattr("app.services.auth.password_configured", lambda: True)
    with _client("203.0.113.7") as c:
        assert c.get("/api/sessions/modules").status_code == 401
        # bramka logowania musi być osiągalna, inaczej nie da się zalogować
        assert c.get("/api/auth/state").status_code == 200


def test_login_flow_sets_cookie(monkeypatch):
    monkeypatch.setattr("app.services.auth.password_configured", lambda: True)
    monkeypatch.setattr("app.services.auth.check_password", lambda p: p == "sekret123")
    with _client("203.0.113.7") as c:
        assert c.post("/api/auth/login", json={"password": "zle"}).status_code == 401
        assert c.post("/api/auth/login", json={"password": "sekret123"}).status_code == 200
        # po zalogowaniu chronione zasoby są dostępne
        assert c.get("/api/sessions/modules").status_code == 200


def test_local_without_password_passes():
    with _client("127.0.0.1") as c:
        assert c.get("/api/sessions/modules").status_code == 200
