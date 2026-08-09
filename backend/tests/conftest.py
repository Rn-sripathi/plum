import json

import pytest

from app.core.config import settings
from app.kb.snapshot import PolicySnapshot


@pytest.fixture(scope="session", autouse=True)
def deterministic_settings():
    """Neutralize developer .env credentials for the app under test.

    The suite must be deterministic and must NEVER touch live stores through
    the app's global settings. Live-credential tests opt in explicitly via
    os.environ (see test_kb.py) — those are unaffected.
    """
    settings.openai_api_key = None
    settings.database_url = None
    settings.qdrant_url = None
    settings.qdrant_api_key = None
    settings.neo4j_uri = None
    settings.neo4j_password = None


@pytest.fixture(scope="session")
def snapshot() -> PolicySnapshot:
    return PolicySnapshot.from_file(settings.policy_terms_path)


@pytest.fixture(scope="session")
def test_cases() -> list[dict]:
    raw = json.loads(settings.test_cases_path.read_text(encoding="utf-8"))
    return raw["test_cases"]
