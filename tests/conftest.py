"""Root pytest configuration and shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to the tests/fixtures directory."""
    return Path(__file__).resolve().parent / "fixtures"
