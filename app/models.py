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

