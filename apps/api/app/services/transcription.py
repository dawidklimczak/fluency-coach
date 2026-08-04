"""Transkrypcja: OpenAI whisper-1 z zachowaniem dysfluencji (spec 4.4).

whisper-1 jest jedynym hostowanym modelem OpenAI z timestamp_granularities.
Nie zmieniać modelu bez przejścia testu dysfluencji (spec 13.1 i 4.4.1).
"""

import logging
from pathlib import Path

from ..config import get_settings
from .seed import seed_config

logger = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-1"


def transcription_enabled() -> bool:
    s = get_settings()
    return bool(s.openai_api_key) and not s.mock_transcription


def transcribe(audio_path: Path) -> dict | None:
    """Zwraca {"text": str, "words": [{word, start, end}]} albo None.

    None = brak transkrypcji (brak klucza, mock albo błąd) - metryki czasowe
    z VAD nadal działają, próba nigdy nie jest blokowana przez Whispera.
    """
    if not transcription_enabled():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=get_settings().openai_api_key)
        disfluency_prompt = seed_config().get("whisper_disfluency_prompt", "")
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
                language="en",
                temperature=0,
                prompt=disfluency_prompt,
            )
        words = [
            {"word": w.word, "start": float(w.start), "end": float(w.end)}
            for w in (result.words or [])
        ]
        return {"text": result.text or "", "words": words}
    except Exception:
        logger.exception("Transkrypcja nie powiodła się dla %s", audio_path)
        return None
