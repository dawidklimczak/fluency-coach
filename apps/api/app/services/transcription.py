"""Transkrypcja: OpenAI whisper-1 z zachowaniem dysfluencji (spec 4.4).

whisper-1 jest jedynym hostowanym modelem OpenAI z timestamp_granularities.
Nie zmieniać modelu bez przejścia testu dysfluencji (spec 13.1 i 4.4.1).
"""

import logging
from pathlib import Path

from ..config import get_settings
from .app_settings import openai_api_key
from .seed import language_config

logger = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-1"


def transcription_enabled() -> bool:
    return bool(openai_api_key()) and not get_settings().mock_transcription


def transcribe_text(audio_path: Path) -> str | None:
    """Sam tekst, bez znaczników czasu - dla krótkich odpowiedzi w rundach Grammar.

    Używa szybszego modelu (ustawienie openai_answer_stt_model), bo tam liczy
    się czas do werdyktu, a czasy słów nie są potrzebne. Bez promptu: niczego
    nie podpowiadamy, żeby rozpoznawanie nie "naprawiało" gramatyki. Gdy szybki
    model zawiedzie, wraca do whisper-1.
    """
    if not transcription_enabled():
        return None
    model = get_settings().openai_answer_stt_model
    if model and model != WHISPER_MODEL:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=openai_api_key(), timeout=30)
            with open(audio_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=model, file=f, language="en", temperature=0
                )
            return (result.text or "").strip()
        except Exception:
            logger.exception("Szybka transkrypcja nie powiodła się, próbuję %s", WHISPER_MODEL)
    fallback = transcribe(audio_path, prompt="")
    return fallback["text"].strip() if fallback else None


def transcribe(audio_path: Path, prompt: str | None = None) -> dict | None:
    """Zwraca {"text": str, "words": [{word, start, end}]} albo None.

    None = brak transkrypcji (brak klucza, mock albo błąd) - metryki czasowe
    z VAD nadal działają, próba nigdy nie jest blokowana przez Whispera.

    prompt=None użyje promptu dysfluencyjnego (spec 4.4). Trener czytania
    podaje pusty łańcuch: przy czytaniu z kartki podpowiedzenie Whisperowi
    czegokolwiek skłaniałoby go do "usłyszenia" oczekiwanego tekstu i ukryłoby
    błędy wymowy, które właśnie chcemy zmierzyć.
    """
    if not transcription_enabled():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key())
        disfluency_prompt = (
            language_config().get("whisper_disfluency_prompt", "")
            if prompt is None
            else prompt
        )
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
