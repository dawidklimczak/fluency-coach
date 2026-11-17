from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = apps/api/app/config.py -> three levels up
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM przez OpenAI - jeden klucz dla Whispera i ocen/generacji
    # (decyzja 2026-08-04, zamiast Anthropic ze spec sekcji 8).
    # Wartość z bazy (ekran ustawień) ma pierwszeństwo - patrz services/app_settings.py
    openai_api_key: str = ""
    openai_llm_model: str = "gpt-4o-mini"
    # Grammar: zadania do banku powstają w tle, więc ten model może być wolniejszy;
    # ocena jednej odpowiedzi (grade) musi wrócić w około sekundę
    openai_grammar_model: str = "gpt-6-sol"
    openai_grade_model: str = "gpt-4.1"
    # rozpoznawanie krótkich odpowiedzi w rundach (bez znaczników czasu, szybsze niż whisper-1)
    openai_answer_stt_model: str = "gpt-4o-mini-transcribe"
    # Shadowing: synteza mowy (nagranie powstaje raz i zostaje na dysku)
    openai_tts_model: str = "gpt-4o-mini-tts"

    # Hasło instancji. Puste = dozwolone tylko lokalnie (localhost).
    # Wystawienie na publiczny interfejs bez hasła jest odrzucane (fail closed).
    app_password: str = ""

    # 1 = nie wywołuj Whispera, metryki językowe puste (czasowe działają z VAD)
    mock_transcription: bool = False

    data_dir: Path = REPO_ROOT / "data"
    web_dist: Path | None = None
    audio_retention_days: int = 30

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def shadow_audio_dir(self) -> Path:
        """Nagrania wzorcowe do shadowingu. Osobno od audio/, bo tamten katalog
        sprząta retencja nagrań użytkownika."""
        return self.data_dir / "shadow"

    @property
    def grammar_skills_path(self) -> Path:
        return self.data_dir / "grammar_skills.json"

    @property
    def grammar_seed_items_path(self) -> Path:
        """Startowy bank zadań dołączony do repo - pierwsza runda nie czeka na LLM."""
        return self.data_dir / "grammar_seed_items.json"

    @property
    def language_config_path(self) -> Path:
        return self.data_dir / "language_config.json"

    @property
    def known_vocabulary_import_path(self) -> Path:
        """Opcjonalny import własnego słownictwa (spec §6 KnownVocabulary)."""
        return self.data_dir / "known_vocabulary_import.json"

    @property
    def vad_model_path(self) -> Path:
        return Path(__file__).resolve().parent / "assets" / "silero_vad.onnx"

    @property
    def instance_key_path(self) -> Path:
        """Klucz do podpisywania ciasteczek sesji - generowany przy pierwszym starcie."""
        return self.data_dir / "instance_key"

    @property
    def web_dist_dir(self) -> Path:
        """Zbudowany frontend (npm run build). Gdy brak - serwujemy samo API.

        W obrazie Dockera ustawiane przez WEB_DIST, bo układ katalogów jest inny.
        """
        return self.web_dist or (REPO_ROOT / "apps" / "web" / "dist")


@lru_cache
def get_settings() -> Settings:
    return Settings()
