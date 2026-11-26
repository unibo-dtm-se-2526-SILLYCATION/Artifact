from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Barrier
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, event

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.dependencies import get_unit_of_work_factory
from sillycation.adapters.persistence.database import create_database
from sillycation.adapters.persistence.unit_of_work import SqliteUnitOfWork
from sillycation.adapters.passwords import Argon2PasswordHasher


PATH = "/api/v1/users"
PASSWORD = "  caffè 🔑  "
BODY = {"username": "Anna", "email": "anna@example.org", "password": PASSWORD}
CONFLICT = {
    "error": {"code": "duplicate", "message": "Resource or action already exists."}
}


def read_users(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(
            "SELECT id, username, email, password_hash FROM users ORDER BY username"
        ).fetchall()


def test_public_registration_persists_exact_password_as_argon2id_across_restart(
    tmp_path,
) -> None:
    database = tmp_path / "api.db"
    with TestClient(create_app()) as client:
        first = client.post(PATH, json=BODY, params={"user_id": "client-selected"})
        second = client.post(
            PATH, json={**BODY, "username": "Luca", "email": "luca@example.org"}
        )
        assert first.status_code == second.status_code == 201
        for response in (first, second):
            assert set(response.json()) == {"id"}
            assert UUID(response.json()["id"]).version == 4
        stored = read_users(database)
        assert [row[0] for row in stored] == [
            first.json()["id"],
            second.json()["id"],
        ]
        assert all(row[3].startswith("$argon2id$") for row in stored)
        assert stored[0][3].split("$")[-2] != stored[1][3].split("$")[-2]
        hasher = Argon2PasswordHasher()
        assert all(hasher.verify(PASSWORD, row[3]) for row in stored)
        assert not hasher.verify(PASSWORD.strip(), stored[0][3])
        with closing(sqlite3.connect(database)) as connection:
            assert [
                row[1] for row in connection.execute("PRAGMA table_info(users)")
            ] == ["id", "username", "email", "password_hash"]

    with TestClient(create_app()) as client:
        assert client.post(PATH, json=BODY).status_code == 409
        assert read_users(database) == stored


@pytest.mark.parametrize(
    "changes", [{"username": "Other"}, {"email": "other@example.org"}]
)
def test_duplicate_leaves_original_user_unchanged(tmp_path, changes) -> None:
    database = tmp_path / "api.db"
    with TestClient(create_app()) as client:
        assert client.post(PATH, json=BODY).status_code == 201
        before = read_users(database)
        response = client.post(
            PATH, json={**BODY, "password": "replacement", **changes}
        )
        assert response.status_code == 409
        assert response.json() == CONFLICT
        assert read_users(database) == before


def test_concurrent_duplicate_has_just_one_winner(tmp_path) -> None:
    ready = Barrier(2, timeout=10)
    app = create_app()
    with TestClient(app) as client:

        def post():
            ready.wait()
            return client.post(PATH, json=BODY)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(post)
            second = pool.submit(post)
            responses = {
                response.status_code: response
                for response in (first.result(15), second.result(15))
            }
        assert set(responses) == {201, 409}
        assert responses[409].json() == CONFLICT
        rows = read_users(tmp_path / "api.db")
        assert len(rows) == 1
        assert rows[0][0] == responses[201].json()["id"]


@pytest.mark.parametrize("conflict", ["id", "username", "email", "not_null"])
def test_actual_sql_constraint_is_classified_after_rollback(
    tmp_path, caplog, conflict
) -> None:
    database = tmp_path / "api.db"
    with TestClient(create_app()) as client:
        first = client.post(PATH, json=BODY)
        assert first.status_code == 201
        before = read_users(database)

        # A trigger on the real database makes the INSERT fail after the
        # application checks, while keeping the registration path unchanged.
        columns = {
            "id": f"'{first.json()['id']}'",
            "username": "'Anna'",
            "email": "'anna@example.org'",
            "not_null": "NULL",
        }
        user_id = columns["id"] if conflict == "id" else "'trigger-id'"
        username = (
            columns[conflict] if conflict in ("username", "not_null") else "'Trigger'"
        )
        email = columns["email"] if conflict == "email" else "'trigger@example.org'"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                f"""
                CREATE TRIGGER fail_registration BEFORE INSERT ON users
                WHEN NEW.username = 'Second'
                BEGIN
                    INSERT INTO users (id, username, email, password_hash)
                    VALUES ({user_id}, {username}, {email}, 'TRIGGER_TEST_VALUE');
                END
                """
            )
            connection.commit()
        response = client.post(
            PATH, json={**BODY, "username": "Second", "email": "second@example.org"}
        )
        if conflict == "not_null":
            assert response.status_code == 500
            assert response.text == "Internal Server Error"
        else:
            assert response.status_code == 409
            assert response.json() == CONFLICT
        assert read_users(database) == before
        assert "$argon2id$" not in caplog.text
        assert "INSERT" not in caplog.text
        assert "second@example.org" not in caplog.text


def test_commit_failure_rolls_back_and_subsequent_registration_succeeds(
    tmp_path, caplog
) -> None:
    database = tmp_path / "api.db"
    with TestClient(create_app()) as client:

        def fail_commit(connection):
            if connection.engine.url.database == str(database):
                raise RuntimeError("PRIVATE_COMMIT_FAILURE")

        event.listen(Engine, "commit", fail_commit)
        try:
            response = client.post(PATH, json=BODY)
        finally:
            event.remove(Engine, "commit", fail_commit)

        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        assert "PRIVATE_COMMIT_FAILURE" not in caplog.text
        assert read_users(database) == []
        assert client.post(PATH, json=BODY).status_code == 201
        assert len(read_users(database)) == 1


def test_sqlite_writer_timeout_is_a_sanitized_technical_failure(
    tmp_path, caplog
) -> None:
    database = tmp_path / "api.db"
    app = create_app()
    engine = create_database(f"sqlite:///{database}")
    try:
        app.dependency_overrides[get_unit_of_work_factory] = lambda: (
            lambda: SqliteUnitOfWork(engine, timeout=0)
        )
        with TestClient(app) as client:
            with SqliteUnitOfWork(engine):
                response = client.post(PATH, json=BODY)
            assert response.status_code == 500
            assert response.text == "Internal Server Error"
            assert "database is locked" not in caplog.text
            assert read_users(database) == []
    finally:
        engine.dispose()


def test_public_validation_does_not_echo_credential_values_or_extra_keys(
    tmp_path,
) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            PATH,
            json={**BODY, "password": {"raw": PASSWORD}, "PRIVATE_EXTRA_KEY": PASSWORD},
        )
    assert response.status_code == 422
    assert PASSWORD not in str(response.json())
    assert "PRIVATE_EXTRA_KEY" not in response.text
    assert read_users(tmp_path / "api.db") == []
