import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .routers import (
    attempts,
    auth as auth_router,
    calibrate,
    learning_sessions,
    sessions,
    settings as settings_router,
    stats,
    tasks,
)
from .services import auth
from .services.retention import cleanup_old_audio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ścieżki dostępne bez zalogowania: sama bramka i health
PUBLIC_PATHS = {"/api/auth/state", "/api/auth/login", "/api/auth/logout", "/api/health"}

FAIL_CLOSED_MESSAGE = (
    "Ta instancja jest dostępna spoza tego komputera, a hasło nie zostało "
    "ustawione. Ustaw zmienną APP_PASSWORD i uruchom ponownie."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cleanup_old_audio()
    s = get_settings()
    if not auth.password_configured():
        logger.warning(
            "APP_PASSWORD nie jest ustawione - aplikacja obsłuży wyłącznie "
            "połączenia z tego komputera (localhost)."
        )
    if not s.web_dist_dir.exists():
        logger.info(
            "Brak zbudowanego frontendu (%s) - serwuję samo API. "
            "Zbuduj go: npm run build w apps/web",
            s.web_dist_dir,
        )
    yield


app = FastAPI(title="Speaking Automaticity Trainer", lifespan=lifespan)

# potrzebne tylko w trybie deweloperskim, gdy frontend chodzi na Vite (:5173);
# przy serwowaniu statyków z tego samego origin nie ma znaczenia
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Bramka: fail closed przy braku hasła na publicznym interfejsie."""
    client_host = request.client.host if request.client else None
    local = auth.is_local_client(client_host)

    if not auth.password_configured() and not local:
        return PlainTextResponse(FAIL_CLOSED_MESSAGE, status_code=503)

    path = request.url.path
    needs_auth = path.startswith("/api/") and path not in PUBLIC_PATHS
    if needs_auth:
        token = request.cookies.get(auth.COOKIE_NAME)
        if not auth.request_authorized(client_host, token):
            return JSONResponse({"detail": "Wymagane zalogowanie"}, status_code=401)

    return await call_next(request)


app.include_router(auth_router.router)
app.include_router(settings_router.router)
app.include_router(learning_sessions.router)
app.include_router(sessions.router)
app.include_router(attempts.router)
app.include_router(calibrate.router)
app.include_router(stats.router)
app.include_router(tasks.router)


@app.get("/api/health")
def health():
    from .services import app_settings

    s = get_settings()
    return {
        "ok": True,
        "vad_model": s.vad_model_path.exists(),
        "transcription": bool(app_settings.openai_api_key()),
        "password_required": auth.password_configured(),
    }


def _mount_frontend() -> None:
    """Serwuje zbudowany frontend z tego samego portu co API (jeden proces).

    Brak katalogu dist nie jest błędem - w trybie deweloperskim frontend
    podaje Vite, a API działa samo.
    """
    dist = get_settings().web_dist_dir
    if not dist.exists():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    for extra in ("ort", "models"):
        if (dist / extra).exists():
            app.mount(f"/{extra}", StaticFiles(directory=dist / extra), name=extra)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # pojedyncze pliki z korzenia (worklet, favicon), reszta -> index.html
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_frontend()
