"""Relational schema: one table per stored domain concept.

Identifiers are stored as their string value and statuses as their enum value.
Participants, join requests and votes are stored in their own tables, but are
always written and read together with the Trip or Episode that owns them.
"""

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", String, primary_key=True),
    Column("username", String, nullable=False, unique=True),
    Column("email", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
)

trips = Table(
    "trips",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, nullable=True),
    Column("creator_id", String, ForeignKey("users.id"), nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("invitation_code", String, nullable=False, unique=True),
    Column("status", String, nullable=False),
)

participants = Table(
    "participants",
    metadata,
    Column("trip_id", String, ForeignKey("trips.id"), primary_key=True),
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
)

join_requests = Table(
    "join_requests",
    metadata,
    Column("id", String, primary_key=True),
    Column("trip_id", String, ForeignKey("trips.id"), nullable=False),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("status", String, nullable=False),
)

episodes = Table(
    "episodes",
    metadata,
    Column("id", String, primary_key=True),
    Column("trip_id", String, ForeignKey("trips.id"), nullable=False),
    Column("author_id", String, ForeignKey("users.id"), nullable=False),
    Column("protagonist_id", String, ForeignKey("users.id"), nullable=False),
    Column("title", String, nullable=False),
    Column("description", String, nullable=False),
    Column("date", Date, nullable=False),
    Column("status", String, nullable=False),
)

votes = Table(
    "votes",
    metadata,
    Column("id", String, primary_key=True),
    Column("episode_id", String, ForeignKey("episodes.id"), nullable=False),
    Column("voter_id", String, ForeignKey("users.id"), nullable=False),
    Column("value", Integer, nullable=False),
    UniqueConstraint("episode_id", "voter_id"),
)
