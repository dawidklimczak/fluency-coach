import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routers import attempts, calibrate, sessions, stats

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Speaking Automaticity Trainer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(attempts.router)
app.include_router(calibrate.router)
app.include_router(stats.router)


@app.get("/api/health")
def health():
    from .config import get_settings
    from .services.transcription import transcription_enabled

    s = get_settings()
    return {
        "ok": True,
        "vad_model": s.vad_model_path.exists(),
        "transcription": transcription_enabled(),
    }
