from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = apps/api/app/config.py -> three levels up
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    # 1 = nie wywołuj Whispera, metryki językowe puste (czasowe działają z VAD)
    mock_transcription: bool = False

    data_dir: Path = REPO_ROOT / "data"
    audio_retention_days: int = 30

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def seed_tasks_path(self) -> Path:
        return self.data_dir / "seed_tasks.json"

    @property
    def vad_model_path(self) -> Path:
        return Path(__file__).resolve().parent / "assets" / "silero_vad.onnx"

    @property
    def drills_dir(self) -> Path:
        return Path(__file__).resolve().parent / "drills"


@lru_cache
def get_settings() -> Settings:
    return Settings()
