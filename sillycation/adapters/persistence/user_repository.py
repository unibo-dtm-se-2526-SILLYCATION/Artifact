"""UserRepository backed by a relational database."""

from typing import Optional

from sqlalchemy import ColumnElement, Engine, insert, select, update

from sillycation.adapters.persistence.tables import users
from sillycation.domain.identifiers import UserId
from sillycation.domain.user import User


class SqlAlchemyUserRepository:
    """Implements the UserRepository port.

    Username and email uniqueness is also enforced by the database: saving a
    duplicate raises sqlalchemy.exc.IntegrityError.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, user: User) -> User:
        with self._engine.begin() as connection:
            values = dict(
                username=user.username,
                email=user.email,
                password_hash=user.password_hash,
            )
            exists = connection.execute(
                select(users.c.id).where(users.c.id == user.id.value)
            ).first()
            if exists is None:
                connection.execute(insert(users).values(id=user.id.value, **values))
            else:
                connection.execute(
                    update(users).where(users.c.id == user.id.value).values(**values)
                )
        return user

    def get_by_id(self, user_id: UserId) -> Optional[User]:
        return self._find(users.c.id == user_id.value)

    def get_by_username(self, username: str) -> Optional[User]:
        return self._find(users.c.username == username)

    def get_by_email(self, email: str) -> Optional[User]:
        return self._find(users.c.email == email)

    def exists_by_username(self, username: str) -> bool:
        return self.get_by_username(username) is not None

    def exists_by_email(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def _find(self, condition: ColumnElement[bool]) -> Optional[User]:
        with self._engine.connect() as connection:
            row = connection.execute(select(users).where(condition)).first()
        if row is None:
            return None
        return User(UserId(row.id), row.username, row.email, row.password_hash)
