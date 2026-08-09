import json

import pytest

from app.core.config import settings
from app.kb.snapshot import PolicySnapshot


@pytest.fixture(scope="session")
def snapshot() -> PolicySnapshot:
    return PolicySnapshot.from_file(settings.policy_terms_path)


@pytest.fixture(scope="session")
def test_cases() -> list[dict]:
    raw = json.loads(settings.test_cases_path.read_text(encoding="utf-8"))
    return raw["test_cases"]
