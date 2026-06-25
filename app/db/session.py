"""SQLModel engine and session helpers."""

from __future__ import annotations

from typing import Generator

from app.config import DATABASE_URL

try:
    from sqlalchemy import text
    from sqlmodel import Session, SQLModel, create_engine
except ImportError:  # pragma: no cover
    Session = None
    SQLModel = None
    create_engine = None
    text = None
    engine = None
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
    )


def get_session() -> Generator:
    """Yield a database session when SQLModel is available."""

    if Session is None or engine is None:
        raise RuntimeError("Database dependencies are not installed.")

    with Session(engine) as session:
        yield session


def create_db_and_tables() -> None:
    """Create tables only for development/tests; use Alembic in production."""

    if SQLModel is None or engine is None:
        raise RuntimeError("Database dependencies are not installed.")

    from app.db import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def check_database_connection() -> bool:
    """Return True when a trivial SELECT 1 succeeds."""

    if Session is None or engine is None or text is None:
        raise RuntimeError("Database dependencies are not installed.")

    with Session(engine) as session:
        session.exec(text("SELECT 1"))
    return True
