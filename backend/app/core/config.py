"""Application settings. Paths default to the repo layout; everything is
overridable via environment variables (prefix PLUM_)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLUM_", env_file=".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    policy_terms_file: Path | None = None
    test_cases_file: Path | None = None

    @property
    def policy_terms_path(self) -> Path:
        return self.policy_terms_file or self.data_dir / "policy_terms.json"

    @property
    def test_cases_path(self) -> Path:
        return self.test_cases_file or self.data_dir / "test_cases.json"


settings = Settings()
