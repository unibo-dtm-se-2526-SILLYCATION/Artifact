import pytest

from sillycation.adapters.persistence.database import DATABASE_URL_VARIABLE


@pytest.fixture(autouse=True)
def isolated_database_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(DATABASE_URL_VARIABLE, f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.delenv("SILLYCATION_AUTH_ENABLED", raising=False)
