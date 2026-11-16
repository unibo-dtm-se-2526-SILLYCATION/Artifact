"""SqlAlchemyUserRepository against a real SQLite database."""

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from sillycation.adapters.persistence.database import create_database
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository
from sillycation.application.ports.repositories import UserRepository
from sillycation.domain.identifiers import UserId
from sillycation.domain.user import User


ANNA = User(UserId("anna"), "Anna", "anna@example.org", "hash-anna")


@pytest.fixture
def users(engine: Engine) -> UserRepository:
    return SqlAlchemyUserRepository(engine)


def test_saved_user_is_found_by_id_with_all_its_data(users: UserRepository) -> None:
    assert users.save(ANNA) == ANNA

    found = users.get_by_id(ANNA.id)

    assert found is not None
    assert found.id == ANNA.id
    assert found.username == "Anna"
    assert found.email == "anna@example.org"
    assert found.password_hash == "hash-anna"


def test_user_is_found_by_username_and_by_email(users: UserRepository) -> None:
    users.save(ANNA)

    assert users.get_by_username("Anna") == ANNA
    assert users.get_by_email("anna@example.org") == ANNA
    assert users.exists_by_username("Anna")
    assert users.exists_by_email("anna@example.org")


def test_unknown_user_is_not_found(users: UserRepository) -> None:
    assert users.get_by_id(UserId("nobody")) is None
    assert users.get_by_username("Nobody") is None
    assert users.get_by_email("nobody@example.org") is None
    assert not users.exists_by_username("Nobody")
    assert not users.exists_by_email("nobody@example.org")


def test_saving_the_same_user_again_keeps_a_single_copy(users: UserRepository) -> None:
    users.save(ANNA)
    users.save(ANNA)

    assert users.get_by_id(ANNA.id) == ANNA


def test_database_rejects_a_duplicate_username(users: UserRepository) -> None:
    users.save(ANNA)

    with pytest.raises(IntegrityError):
        users.save(User(UserId("other"), "Anna", "other@example.org", "hash"))


def test_database_rejects_a_duplicate_email(users: UserRepository) -> None:
    users.save(ANNA)

    with pytest.raises(IntegrityError):
        users.save(User(UserId("other"), "Other", "anna@example.org", "hash"))


def test_users_survive_an_application_restart(database_url: str) -> None:
    first_run = create_database(database_url)
    SqlAlchemyUserRepository(first_run).save(ANNA)
    first_run.dispose()

    second_run = create_database(database_url)
    found = SqlAlchemyUserRepository(second_run).get_by_id(ANNA.id)
    second_run.dispose()

    assert found == ANNA
