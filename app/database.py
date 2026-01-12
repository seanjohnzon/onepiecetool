from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base, PriceHistory, CalcConfig, ConfigLog


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
        
        # Original columns
        if "market_url" not in existing_cols:
            conn.execute(text("ALTER TABLE cards ADD COLUMN market_url VARCHAR(255)"))
        if "language" not in existing_cols:
            conn.execute(text("ALTER TABLE cards ADD COLUMN language VARCHAR(32)"))
        
        # New SMA/EMA columns
        new_cols = [
            ("sma_30", "FLOAT"),
            ("ema_30", "FLOAT"),
            ("trend_score_sma", "FLOAT"),
            ("trend_score_ema", "FLOAT"),
            ("total_score_sma", "FLOAT"),
            ("total_score_ema", "FLOAT"),
            ("flip_score", "FLOAT"),
            ("last_trend_calc", "DATE"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE cards ADD COLUMN {col_name} {col_type}"))


def ensure_new_tables() -> None:
    """
    Create new tables for price history and configuration.
    Safe to run multiple times - won't affect existing tables.
    """
    
    # Create tables if they don't exist
    Base.metadata.create_all(engine, tables=[
        PriceHistory.__table__,
        CalcConfig.__table__,
        ConfigLog.__table__,
    ])


def seed_default_config() -> None:
    """
    Insert default configuration values if not already present.
    """
    
    defaults = [
        # SMA settings
        ("sma_period", 30, "Days for SMA calculation", 7, 90),
        ("sma_weight", 0.5, "SMA trend contribution to total score", 0, 2),
        # EMA settings  
        ("ema_period", 30, "Days for EMA calculation", 7, 90),
        ("ema_smoothing", 2.0, "EMA smoothing: k = value/(period+1)", 1, 3),
        ("ema_weight", 0.5, "EMA trend contribution to total score", 0, 2),
        # Trend caps
        ("trend_cap", 50, "Max absolute trend score (+/-)", 10, 100),
        # Price bonuses
        ("sweet_low", 15, "Sweet spot lower bound ($)", 5, 50),
        ("sweet_high", 100, "Sweet spot upper bound ($)", 50, 500),
        ("sweet_bonus", 1.2, "Multiplier for sweet spot range", 1.0, 2.0),
        ("mid_low", 100, "Mid range lower bound ($)", 50, 200),
        ("mid_high", 500, "Mid range upper bound ($)", 200, 1000),
        ("mid_bonus", 1.0, "Multiplier for mid range", 0.5, 1.5),
        ("high_bonus", 0.8, "Multiplier for high price (>mid_high)", 0.5, 1.0),
        ("low_bonus", 0.9, "Multiplier for low price (<sweet_low)", 0.5, 1.0),
        # Thresholds
        ("min_variants", 4, "Min variants per character for inclusion", 2, 10),
        ("min_char_avg", 30, "Min character average ($)", 10, 100),
        ("min_price", 10, "Min card price for flip candidates ($)", 5, 50),
        ("min_history_days", 7, "Min days of price history before trends", 3, 30),
    ]
    
    with engine.begin() as conn:
        for key, value, note, min_b, max_b in defaults:
            # Only insert if not exists
            existing = conn.execute(
                text("SELECT key FROM calc_config WHERE key = :key"),
                {"key": key}
            ).fetchone()
            if not existing:
                conn.execute(
                    text("""
                        INSERT INTO calc_config (key, value, note, min_bound, max_bound)
                        VALUES (:key, :value, :note, :min_bound, :max_bound)
                    """),
                    {"key": key, "value": value, "note": note, "min_bound": min_b, "max_bound": max_b}
                )


def init_database() -> None:
    """
    Initialize database with all migrations and seeds.
    Safe to call on every app startup.
    """
    ensure_new_tables()
    ensure_columns()
    seed_default_config()
