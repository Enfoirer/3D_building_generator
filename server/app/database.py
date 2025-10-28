from __future__ import annotations

import os
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine


def _build_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        # Fallback to SQLite for situations where Postgres is unavailable.
        database_url = "sqlite:///./data/app.db"

    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(database_url, echo=False, pool_pre_ping=True, connect_args=connect_args)


engine = _build_engine()


def init_db() -> None:
    """
    Create all tables if they do not exist. This runs on FastAPI startup.
    """
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope() -> Session:
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session():
    with Session(engine) as session:
        yield session
