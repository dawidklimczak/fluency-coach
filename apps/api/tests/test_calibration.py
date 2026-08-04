"""Test krytyczny 13.3: kalibracja VAD przy trzech poziomach szumu tła.

Ten sam materiał mowy zmiksowany z szumem; po kalibracji liczba wykrytych pauz
nie może różnić się o więcej niż 1 między wariantami.
"""

import numpy as np
import pytest

from conftest import SAMPLE_RATE, load_wav, silence, trim_to_speech

NOISE_LEVELS = [0.0005, 0.005, 0.02]


@pytest.fixture(scope="module")
def vad_module(vad_model_available):
    from app.services import vad

    return vad


def _pause_count(segments) -> int:
    gaps = [b[0] - a[1] for a, b in zip(segments, segments[1:])]
    return sum(1 for g in gaps if g >= 0.25)


def test_calibration_stability_across_noise(fixtures_dir, vad_module):
    phrase = trim_to_speech(load_wav(fixtures_dir / "phrase.wav"))
    base = np.concatenate([phrase, silence(0.5), phrase, silence(1.2), phrase])

    rng = np.random.default_rng(42)
    counts = []
    for level in NOISE_LEVELS:
        noise_cal = (rng.normal(0, level, 10 * SAMPLE_RATE)).astype(np.float32)
        _, threshold = vad_module.calibrate(noise_cal)

        noise = (rng.normal(0, level, len(base))).astype(np.float32)
        mixed = np.clip(base + noise, -1, 1)
        segments = vad_module.get_vad().speech_segments(mixed, threshold=threshold)
        counts.append(_pause_count(segments))

    assert max(counts) - min(counts) <= 1, (
        f"liczba pauz niestabilna między poziomami szumu: {counts}"
    )
    assert all(c >= 1 for c in counts), f"pauzy zniknęły przy szumie: {counts}"
