"""Application settings. Paths default to the repo layout; everything is
overridable via environment variables (PLUM_ prefix unless noted)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLUM_", env_file=".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    policy_terms_file: Path | None = None
    test_cases_file: Path | None = None
    database_file: Path | None = None

    # LLM (real-mode document classification/extraction). Absent key = the
    # pipeline runs deterministically on declared types + supplied content.
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = "gpt-4o"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    upload_dir: Path | None = None

    @property
    def policy_terms_path(self) -> Path:
        return self.policy_terms_file or self.data_dir / "policy_terms.json"

    @property
    def test_cases_path(self) -> Path:
        return self.test_cases_file or self.data_dir / "test_cases.json"

    @property
    def database_path(self) -> Path:
        return self.database_file or self.data_dir / "claims.db"

    @property
    def upload_path(self) -> Path:
        return self.upload_dir or self.data_dir / "uploads"


settings = Settings()
