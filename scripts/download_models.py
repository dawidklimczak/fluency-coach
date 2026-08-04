"""Pobiera model Silero VAD (ONNX, v4) do backendu i frontendu.

v4 celowo: proste wejścia (input, sr, h, c), identyczna obsługa w onnxruntime
(Python) i onnxruntime-web (przeglądarka). Uruchomienie: python scripts/download_models.py
"""

import urllib.request
from pathlib import Path

URL = "https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx"

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "apps" / "api" / "app" / "assets" / "silero_vad.onnx",
    ROOT / "apps" / "web" / "public" / "models" / "silero_vad.onnx",
]


def main() -> None:
    data = None
    for target in TARGETS:
        if target.exists() and target.stat().st_size > 100_000:
            print(f"OK (jest): {target}")
            continue
        if data is None:
            print(f"Pobieram {URL} ...")
            with urllib.request.urlopen(URL) as r:
                data = r.read()
            print(f"Pobrano {len(data)} bajtów")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"Zapisano: {target}")


if __name__ == "__main__":
    main()
