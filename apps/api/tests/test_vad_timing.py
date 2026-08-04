"""Testy krytyczne 13.2: dokładność ttfw i wykrywania pauz o znanej długości."""

import numpy as np
import pytest

from conftest import load_wav, silence, trim_to_speech


@pytest.fixture(scope="module")
def vad_service(vad_model_available):
    from app.services.vad import get_vad

    return get_vad()


def test_ttfw_accuracy(fixtures_dir, vad_service):
    """2.0 s ciszy + mowa -> zmierzone ttfw w 2.0 s +/- 100 ms."""
    speech = trim_to_speech(load_wav(fixtures_dir / "speech.wav"))
    audio = np.concatenate([silence(2.0), speech])

    segments = vad_service.speech_segments(audio)
    assert segments, "VAD nie wykrył mowy w nagraniu TTS"

    ttfw = segments[0][0]
    assert ttfw == pytest.approx(2.0, abs=0.1), f"ttfw={ttfw:.3f}, oczekiwano 2.0 +/- 0.1"


@pytest.mark.parametrize("pause_s", [0.3, 0.5, 1.5])
def test_known_pause_duration(fixtures_dir, vad_service, pause_s):
    """Fraza + cisza o znanej długości + fraza -> zmierzona przerwa zgodna z zadaną."""
    phrase = trim_to_speech(load_wav(fixtures_dir / "phrase.wav"))
    audio = np.concatenate([phrase, silence(pause_s), phrase])

    segments = vad_service.speech_segments(audio)
    gaps = [b[0] - a[1] for a, b in zip(segments, segments[1:])]
    internal = [g for g in gaps if g >= 0.25]

    assert len(internal) == 1, f"oczekiwano 1 pauzy >= 250 ms, wykryto {internal}"
    assert internal[0] == pytest.approx(pause_s, abs=0.15), (
        f"pauza {internal[0]:.3f} s, oczekiwano {pause_s} s"
    )


def test_pause_below_threshold_not_counted(fixtures_dir, vad_service):
    """Przerwa 0.1 s nie może rozdzielić wypowiedzi na pauzę >= 250 ms."""
    phrase = trim_to_speech(load_wav(fixtures_dir / "phrase.wav"))
    audio = np.concatenate([phrase, silence(0.1), phrase])

    segments = vad_service.speech_segments(audio)
    gaps = [b[0] - a[1] for a, b in zip(segments, segments[1:])]
    assert all(g < 0.25 for g in gaps), f"fałszywa pauza >= 250 ms: {gaps}"
