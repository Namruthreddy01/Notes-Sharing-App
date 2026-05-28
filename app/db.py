from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _db_url() -> str:
    # Default to a local SQLite file inside the project.
    return os.environ.get("DATABASE_URL", "sqlite:///./app.db")


engine = create_engine(
    _db_url(),
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
