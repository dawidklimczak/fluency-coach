"""Siatka bezpieczeństwa dla retencji audio (spec §6): normalnie audio jest
kasowane od razu po analizie w tym samym przebiegu przetwarzania (Attempt
i ReadingAttempt nie zostawiają plików na dysku). Ten sweep sprząta jedynie
to, co zostało po przerwanym/awaryjnym przetwarzaniu."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import get_settings
from ..db import db_session
from ..models import Attempt

logger = logging.getLogger(__name__)


def cleanup_old_audio() -> int:
    settings = get_settings()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=settings.audio_retention_days)
    ).isoformat()

    db = db_session()
    removed = 0
    try:
        old = (
            db.query(Attempt)
            .filter(Attempt.created_at < cutoff, Attempt.audio_path.isnot(None))
            .all()
        )
        for attempt in old:
            path = Path(attempt.audio_path)
            try:
                if path.exists():
                    path.unlink()
                attempt.audio_path = None
                removed += 1
            except OSError:
                logger.warning("Nie udało się usunąć %s", path)
        db.commit()
        # puste katalogi sesji po sprzątnięciu plików
        audio_dir = settings.audio_dir
        if audio_dir.exists():
            for d in audio_dir.iterdir():
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
    finally:
        db.close()
    if removed:
        logger.info("Retencja: usunięto %d plików audio", removed)
    return removed
