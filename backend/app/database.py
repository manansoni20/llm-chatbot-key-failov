"""SQLite database engine, session factory, and initialization helpers."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def _ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory for file-backed SQLite databases if missing."""
    if not database_url.startswith("sqlite:///"):
        return

    db_path_str = database_url.removeprefix("sqlite:///")
    if not db_path_str or db_path_str == ":memory:":
        return

    db_path = Path(db_path_str)
    if db_path.parent and str(db_path.parent) != ".":
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _create_db_engine(database_url: str) -> Engine:
    """Create the SQLAlchemy engine configured for SQLite."""
    _ensure_sqlite_directory(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}

    db_engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
    )

    if database_url.startswith("sqlite"):
        is_memory = database_url.endswith(":memory:")

        @event.listens_for(db_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if not is_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return db_engine


settings = get_settings()
engine = _create_db_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def init_db() -> None:
    """Import ORM models and create all database tables if they do not exist."""
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session per request and close it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
