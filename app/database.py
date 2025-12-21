from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """
    Yield a database session for request handling.

    Yields:
        Session: SQLAlchemy session.
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns() -> None:
    """
    Ensure new columns exist on the cards table (lightweight SQLite migration).
    """

    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        info = conn.execute(text("PRAGMA table_info(cards)")).fetchall()
        existing_cols = {row[1] for row in info}
        if "market_url" not in existing_cols:
            conn.execute(text("ALTER TABLE cards ADD COLUMN market_url VARCHAR(255)"))
        if "language" not in existing_cols:
            conn.execute(text("ALTER TABLE cards ADD COLUMN language VARCHAR(32)"))

