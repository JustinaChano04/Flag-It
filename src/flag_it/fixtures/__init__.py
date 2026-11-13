"""Shared example records for tests. Built by flag_it.fixtures.build into fixtures/."""

import os
from pathlib import Path

_REPO_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def fixtures_dir() -> Path:
    """FLAG_IT_FIXTURES_PATH if set (installed copies), else the repo's fixtures/ folder."""
    return Path(os.environ.get("FLAG_IT_FIXTURES_PATH", _REPO_FIXTURES))
