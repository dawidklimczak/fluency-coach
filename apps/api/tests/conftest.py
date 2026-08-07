import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES = TESTS_DIR / "fixtures"

sys.path.insert(0, str(TESTS_DIR.parent))

# Izolacja: testy nie mogą dotykać bazy i nagrań użytkownika. DATA_DIR musi
# być ustawione ZANIM cokolwiek zaimportuje app.db (silnik powstaje przy imporcie).
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="sat-tests-"))
shutil.copy(
    TESTS_DIR.parents[2] / "data" / "seed_tasks.json",
    _TEST_DATA_DIR / "seed_tasks.json",
)
os.environ["DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ.pop("APP_PASSWORD", None)

SAMPLE_RATE = 16000


def _generate_fixtures() -> None:
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(TESTS_DIR / "gen_fixtures.ps1"),
        ],
        check=True,
        capture_output=True,
    )


def _ensure_fixtures() -> bool:
    needed = ["phrase.wav", "speech.wav", "disfluent.wav"]
    if all((FIXTURES / n).exists() for n in needed):
        return True
    if sys.platform != "win32":
        return False
    try:
        _generate_fixtures()
    except Exception:
        return False
    return all((FIXTURES / n).exists() for n in needed)


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def save_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


def trim_to_speech(audio: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Przycina nagranie do granic sygnału po amplitudzie (niezależnie od VAD)."""
    idx = np.where(np.abs(audio) > threshold)[0]
    if len(idx) == 0:
        return audio
    return audio[idx[0] : idx[-1] + 1]


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    if not _ensure_fixtures():
        pytest.skip("Brak fixtur audio (generacja TTS dostępna tylko na Windows)")
    return FIXTURES


@pytest.fixture(scope="session")
def vad_model_available() -> None:
    from app.config import get_settings

    if not get_settings().vad_model_path.exists():
        pytest.skip("Brak modelu silero_vad.onnx - uruchom scripts/download_models.py")
