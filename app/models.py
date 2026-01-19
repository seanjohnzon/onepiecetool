from datetime import date, datetime
from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class Card(Base):
    """Database model for a One Piece TCG card entry."""

    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("set_code", "card_number", "variant", name="uq_card_identity"),
    )

    id = Column(Integer, primary_key=True, index=True)
    set_code = Column(String(32), nullable=False, index=True)
    card_name = Column(String(255), nullable=False, index=True)
    card_number = Column(String(32), nullable=False, index=True)
    variant = Column(String(64), nullable=True, index=True)
    scarcity = Column(String(128), nullable=True)
    price = Column(Float, nullable=True)
    buy_under = Column(Float, nullable=True)
    priority_manual = Column(Integer, nullable=True, index=True)
    priority_logic = Column(Text, nullable=True)
    strategy = Column(String(64), nullable=True)
    hold_period = Column(String(64), nullable=True)
    liquidity = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    price_source = Column(String(128), nullable=True)
    last_checked = Column(Date, nullable=True)
    price_1y = Column(Float, nullable=True)
    roi_1y = Column(Float, nullable=True)
    price_3y = Column(Float, nullable=True)
    roi_3y = Column(Float, nullable=True)
    momentum_score = Column(Float, nullable=True)
    rarity_score = Column(Float, nullable=True)
    value_score = Column(Float, nullable=True)
    auto_priority_value = Column(Float, nullable=True)
    tcgplayer_search = Column(String(255), nullable=True)
    auto_priority_rank = Column(Integer, nullable=True)
    image_path = Column(String(255), nullable=True)
    image_url = Column(String(255), nullable=True)
    market_url = Column(String(255), nullable=True)
    language = Column(String(32), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # SMA/EMA trend analysis columns (added for flip score enhancement)
    sma_30 = Column(Float, nullable=True)  # 30-day Simple Moving Average
    ema_30 = Column(Float, nullable=True)  # 30-day Exponential Moving Average
    trend_score_sma = Column(Float, nullable=True)  # SMA-based trend score
    trend_score_ema = Column(Float, nullable=True)  # EMA-based trend score
    total_score_sma = Column(Float, nullable=True)  # Static + SMA trend
    total_score_ema = Column(Float, nullable=True)  # Static + EMA trend
    flip_score = Column(Float, nullable=True)  # Static flip score (our formula)
    last_trend_calc = Column(Date, nullable=True)  # When trends were last calculated

    # Supply/Demand data from PriceCharting (for Golden Ratio formula)
    sales_volume_text = Column(String(64), nullable=True)  # Raw: "3 sales per week"
    sales_per_week = Column(Float, nullable=True)  # Normalized: 3.0 (sales/week)
    active_listings = Column(Integer, nullable=True)  # Supply: how many listed for sale
    price_change = Column(Float, nullable=True)  # Recent price movement (+$X.XX)
    release_date = Column(Date, nullable=True)  # Card/Set release date
    supply_score = Column(Float, nullable=True)  # Calculated scarcity (0-100)
    demand_score = Column(Float, nullable=True)  # Calculated demand (0-100)
    golden_ratio_score = Column(Float, nullable=True)  # Final combined flip score
    last_market_sync = Column(DateTime, nullable=True)  # When market data was last synced


class PriceHistory(Base):
    """
    Stores daily price snapshots for trend analysis.
    
    Used to calculate SMA and EMA over time.
    """

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("card_id", "recorded_at", name="uq_price_history_card_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    card_id = Column(Integer, nullable=False, index=True)
    price = Column(Float, nullable=False)
    recorded_at = Column(Date, nullable=False, index=True)
    source = Column(String(64), nullable=True, default="pricecharting")


class CalcConfig(Base):
    """
    Configuration table for tunable calculation parameters.
    
    AI-managed, not exposed to users. Allows adjusting math
    without code changes.
    """

    __tablename__ = "calc_config"

    key = Column(String(64), primary_key=True)
    value = Column(Float, nullable=False)
    note = Column(Text, nullable=True)
    min_bound = Column(Float, nullable=True)
    max_bound = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now())


class ConfigLog(Base):
    """
    Audit log for configuration changes.
    
    Tracks what changed, when, and why for rollback capability.
    """

    __tablename__ = "config_log"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(64), nullable=False)
    old_value = Column(Float, nullable=True)
    new_value = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    changed_at = Column(DateTime, nullable=False, server_default=func.now())


class SavedLot(Base):
    """
    Represents a saved collection of cards (a "lot").
    """

    __tablename__ = "saved_lots"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    total_value = Column(Float, nullable=True)
    card_count = Column(Integer, nullable=True)
    card_ids = Column(Text, nullable=True)  # JSON array of card IDs
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
