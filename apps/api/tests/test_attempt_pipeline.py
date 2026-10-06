"""Jednostkowy test app.services.attempt_pipeline.process_attempt: flaga
skip_language_metrics (spec zmian §2.3 - kontrola native-language nie powinna
odpalać spaCy/lang_metrics, które zakładają angielski)."""

import wave
from pathlib import Path

import pytest

from app.db import Base, SessionLocal, engine
from app.models import Attempt
from app.services import attempt_pipeline, lang_metrics, transcription, vad


@pytest.fixture
def db():
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()


def _write_silence_wav(path: Path, seconds: float = 1.0, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))


def test_skip_language_metrics_flag_bypasses_lang_metrics(db, tmp_path, monkeypatch):
    wav_path = tmp_path / "attempt.wav"
    _write_silence_wav(wav_path)

    attempt = Attempt(audio_path=str(wav_path), status="processing")
    db.add(attempt)
    db.commit()

    # symulujemy mowę i transkrypcję, żeby lang_metrics w ogóle miałby co robić
    monkeypatch.setattr(
        vad.get_vad(), "speech_segments", lambda audio, threshold=0.5: [(0.0, 1.0)]
    )
    monkeypatch.setattr(
        transcription, "transcribe",
        lambda path, prompt=None: {"text": "hello there", "words": [
            {"word": "hello", "start": 0.0, "end": 0.3},
            {"word": "there", "start": 0.3, "end": 0.6},
        ]},
    )
    called = {"count": 0}
    original = lang_metrics.compute_language_metrics

    def spy(*args, **kwargs):
        called["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(lang_metrics, "compute_language_metrics", spy)

    attempt_pipeline.process_attempt(attempt.id, skip_language_metrics=True)

    assert called["count"] == 0
    db.refresh(attempt)
    assert attempt.status == "done"
    assert attempt.transcript == "hello there"
