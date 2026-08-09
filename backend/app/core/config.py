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
    embedding_model: str = "text-embedding-3-small"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # Knowledge/persistence stores — each is optional and independently
    # activated by its env var; absent = the documented fallback runs.
    database_url: str | None = Field(
        default=None, validation_alias="DATABASE_URL",
        description="Postgres DSN (e.g. Neon). Absent -> SQLite.",
    )
    qdrant_url: str | None = Field(
        default=None, validation_alias="QDRANT_URL",
        description="Qdrant Cloud URL. Absent -> embedded local index.",
    )
    qdrant_api_key: str | None = Field(default=None, validation_alias="QDRANT_API_KEY")
    qdrant_local_dir: Path | None = None
    neo4j_uri: str | None = Field(
        default=None, validation_alias="NEO4J_URI",
        description="Neo4j AuraDB bolt/neo4j+s URI. Absent -> snapshot only.",
    )
    neo4j_username: str = Field(default="neo4j", validation_alias="NEO4J_USERNAME")
    neo4j_password: str | None = Field(default=None, validation_alias="NEO4J_PASSWORD")

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

    @property
    def qdrant_local_path(self) -> Path:
        return self.qdrant_local_dir or self.data_dir / "qdrant"


settings = Settings()
