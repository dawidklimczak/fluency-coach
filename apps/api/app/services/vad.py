"""Serwerowy Silero VAD (ONNX, CPU) - źródło prawdy dla wszystkich metryk czasowych.

Model: silero-vad v4 (wejścia: input, sr, h, c). Okno 512 próbek przy 16 kHz (~32 ms).
Parametry segmentacji wg spec 4.3: threshold=0.5 (korygowany kalibracją),
min_speech_duration_ms=100, min_silence_duration_ms=200, speech_pad_ms=0.
"""

import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort

from ..config import get_settings

SAMPLE_RATE = 16000
WINDOW = 512
FRAME_S = WINDOW / SAMPLE_RATE


class SileroVAD:
    def __init__(self, model_path: Path):
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )

    def speech_probs(self, audio: np.ndarray) -> np.ndarray:
        """Prawdopodobieństwo mowy per okno 512 próbek."""
        audio = audio.astype(np.float32)
        h = np.zeros((2, 1, 64), dtype=np.float32)
        c = np.zeros((2, 1, 64), dtype=np.float32)
        sr = np.array(SAMPLE_RATE, dtype=np.int64)
        probs = []
        n_frames = len(audio) // WINDOW
        for i in range(n_frames):
            chunk = audio[i * WINDOW : (i + 1) * WINDOW]
            out, h, c = self.session.run(
                None, {"input": chunk[None, :], "sr": sr, "h": h, "c": c}
            )
            probs.append(float(out.squeeze()))
        return np.array(probs, dtype=np.float32)

    def speech_segments(
        self,
        audio: np.ndarray,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 100,
        min_silence_duration_ms: int = 200,
    ) -> list[tuple[float, float]]:
        """Segmenty mowy [(start_s, end_s), ...] - logika jak w silero get_speech_timestamps."""
        probs = self.speech_probs(audio)
        neg_threshold = max(threshold - 0.15, 0.01)
        min_speech_frames = max(1, int(min_speech_duration_ms / 1000 / FRAME_S))
        min_silence_frames = max(1, int(min_silence_duration_ms / 1000 / FRAME_S))

        segments: list[tuple[float, float]] = []
        triggered = False
        start_frame = 0
        silence_run = 0

        for i, p in enumerate(probs):
            if not triggered:
                if p >= threshold:
                    triggered = True
                    start_frame = i
                    silence_run = 0
            else:
                if p < neg_threshold:
                    silence_run += 1
                    if silence_run >= min_silence_frames:
                        end_frame = i - silence_run + 1
                        if end_frame - start_frame >= min_speech_frames:
                            segments.append(
                                (start_frame * FRAME_S, end_frame * FRAME_S)
                            )
                        triggered = False
                        silence_run = 0
                else:
                    silence_run = 0

        if triggered:
            end_frame = len(probs) - silence_run
            if end_frame - start_frame >= min_speech_frames:
                segments.append((start_frame * FRAME_S, end_frame * FRAME_S))

        return segments


@lru_cache
def get_vad() -> SileroVAD:
    return SileroVAD(get_settings().vad_model_path)


def read_wav_mono16k(path: Path | str) -> np.ndarray:
    """Wczytuje WAV PCM 16-bit; wymaga mono 16 kHz (tak koduje frontend)."""
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sr = wf.getframerate()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if sampwidth != 2:
        raise ValueError(f"Oczekiwano PCM 16-bit, jest {sampwidth * 8}-bit")
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)
    if sr != SAMPLE_RATE:
        # awaryjny resampling liniowy - frontend wysyła 16 kHz, więc to ścieżka wyjątkowa
        duration = len(audio) / sr
        n_out = int(duration * SAMPLE_RATE)
        audio = np.interp(
            np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio
        ).astype(np.float32)
    return audio


def noise_floor_db(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    return 20.0 * np.log10(max(rms, 1e-6))


def calibrate(audio: np.ndarray) -> tuple[float, float]:
    """Z 10 s ciszy w pomieszczeniu użytkownika wyznacza poziom szumu i próg VAD.

    Próg = 99. percentyl prawdopodobieństwa mowy na ciszy + margines 0.15,
    obcięty do [0.5, 0.9]. W cichym pokoju zostaje 0.5, w głośnym rośnie.
    """
    floor = noise_floor_db(audio)
    probs = get_vad().speech_probs(audio)
    p99 = float(np.quantile(probs, 0.99)) if len(probs) else 0.0
    threshold = float(np.clip(p99 + 0.15, 0.5, 0.9))
    return floor, threshold
