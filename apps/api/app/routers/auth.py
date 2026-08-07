"""Logowanie hasłem instancji. Bez loginu - aplikacja jest jednoosobowa."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str


@router.get("/state")
def state(request: Request):
    """Stan bramki - frontend woła to przy starcie, przed czymkolwiek innym."""
    local = auth.is_local_client(request.client.host if request.client else None)
    configured = auth.password_configured()
    token = request.cookies.get(auth.COOKIE_NAME)
    return {
        "password_required": configured,
        "authenticated": (not configured and local) or auth.verify_token(token),
        "local": local,
    }


@router.post("/login")
def login(body: LoginBody, response: Response, request: Request):
    if not auth.password_configured():
        return {"ok": True, "note": "Hasło nie jest ustawione"}
    if not auth.check_password(body.password):
        response.status_code = 401
        return {"ok": False, "error": "Nieprawidłowe hasło"}

    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_token(),
        max_age=auth.SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}
