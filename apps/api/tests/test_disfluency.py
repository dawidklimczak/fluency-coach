"""Test krytyczny 13.1: zachowanie dysfluencji w transkrypcji Whispera.

Wymaga OPENAI_API_KEY (wywołuje prawdziwe API) - bez klucza jest pomijany.
Jeśli konfiguracja Whispera zostanie zmieniona i ten test padnie, metryki
językowe są bezwartościowe (spec 13.1).
"""

import pytest


def _has_key() -> bool:
    from app.config import get_settings

    return bool(get_settings().openai_api_key)

EXPECTED_FILLERS = ["um", "uh", "you know", "i mean", "right"]
# powtórzenia: fraza musi wystąpić co najmniej 2 razy (między powtórzeniami
# może być wtrącenie, np. "I was, uh, I was")
EXPECTED_REPETITIONS = ["i was", "we could", "it's"]
# akceptowane warianty zapisu tego samego dźwięku
VARIANTS = {
    "um": ["um", "erm", "uhm"],
    "uh": ["uh", "er,", "uhh"],
}


@pytest.mark.skipif(not _has_key(), reason="brak OPENAI_API_KEY w .env")
def test_whisper_preserves_disfluencies(fixtures_dir):
    from app.services.transcription import transcribe

    result = transcribe(fixtures_dir / "disfluent.wav")
    assert result is not None, "transkrypcja nie zwróciła wyniku"
    text = result["text"].lower()

    found = 0
    missing = []
    for item in EXPECTED_FILLERS:
        variants = VARIANTS.get(item, [item])
        if any(v in text for v in variants):
            found += 1
        else:
            missing.append(item)
    for item in EXPECTED_REPETITIONS:
        if text.count(item) >= 2:
            found += 1
        else:
            missing.append(f"powtórzenie: {item}")

    total = len(EXPECTED_FILLERS) + len(EXPECTED_REPETITIONS)
    ratio = found / total
    assert ratio >= 0.8, (
        f"zachowano {ratio:.0%} dysfluencji (wymagane >= 80%). "
        f"Brakuje: {missing}. Transkrypcja: {text!r}"
    )

    assert result["words"], "brak timestampów słów (timestamp_granularities)"
