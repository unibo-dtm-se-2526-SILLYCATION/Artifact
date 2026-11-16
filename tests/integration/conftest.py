"""Shared fixtures: every test gets its own empty SQLite database file."""

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import Engine

from sillycation.adapters.persistence.database import create_database


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_database(database_url)
    yield engine
    engine.dispose()
