from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CardBase(BaseModel):
    """Shared fields for card objects."""

    set_code: Optional[str] = Field(None, description="Set code, e.g., OP-05")
    card_name: Optional[str] = Field(None, description="Card or character name")
    card_number: Optional[str] = Field(None, description="Card number such as OP05-098")
    variant: Optional[str] = Field(None, description="Variant/SP/Leader, etc.")
    scarcity: Optional[str] = Field(None, description="Scarcity label")
    price: Optional[float] = Field(None, description="Current market price")
    buy_under: Optional[float] = Field(None, description="Target buy-under price")
    priority_manual: Optional[int] = Field(None, description="Manual priority rank (lower is better)")
    priority_logic: Optional[str] = Field(None, description="Reasoning behind priority")
    strategy: Optional[str] = Field(None, description="Flip/Invest/etc.")
    hold_period: Optional[str] = Field(None, description="Suggested hold period")
    liquidity: Optional[str] = Field(None, description="Liquidity assessment")
    notes: Optional[str] = Field(None, description="Additional notes")
    price_source: Optional[str] = Field(None, description="Source of price data")
    last_checked: Optional[date] = Field(None, description="When the price was last checked")
    price_1y: Optional[float] = Field(None, description="Price one year ago")
    roi_1y: Optional[float] = Field(None, description="ROI percentage over one year")
    price_3y: Optional[float] = Field(None, description="Price three years ago")
    roi_3y: Optional[float] = Field(None, description="ROI percentage over three years")
    momentum_score: Optional[float] = Field(None, description="Manual momentum score")
    rarity_score: Optional[float] = Field(None, description="Rarity score")
    value_score: Optional[float] = Field(None, description="Rarity/price derived score")
    auto_priority_value: Optional[float] = Field(None, description="Auto priority derived from value score")
    tcgplayer_search: Optional[str] = Field(None, description="TCGPlayer search helper")
    auto_priority_rank: Optional[int] = Field(None, description="Auto priority rank output")
    image_url: Optional[str] = Field(None, description="External image URL if available")
    market_url: Optional[str] = Field(None, description="Listing/reference URL (e.g., PriceCharting)")
    language: Optional[str] = Field(None, description="Card language (e.g., English, Japanese)")


class CardCreate(CardBase):
    """Payload for creating a card."""


class CardUpdate(BaseModel):
    """Payload for partial card updates."""

    set_code: Optional[str] = None
    card_name: Optional[str] = None
    card_number: Optional[str] = None
    variant: Optional[str] = None
    scarcity: Optional[str] = None
    price: Optional[float] = None
    buy_under: Optional[float] = None
    priority_manual: Optional[int] = None
    priority_logic: Optional[str] = None
    strategy: Optional[str] = None
    hold_period: Optional[str] = None
    liquidity: Optional[str] = None
    notes: Optional[str] = None
    price_source: Optional[str] = None
    last_checked: Optional[date] = None
    price_1y: Optional[float] = None
    roi_1y: Optional[float] = None
    price_3y: Optional[float] = None
    roi_3y: Optional[float] = None
    momentum_score: Optional[float] = None
    rarity_score: Optional[float] = None
    value_score: Optional[float] = None
    auto_priority_value: Optional[float] = None
    tcgplayer_search: Optional[str] = None
    auto_priority_rank: Optional[int] = None
    image_url: Optional[str] = None
    market_url: Optional[str] = None
    language: Optional[str] = None


class SaveLotRequest(BaseModel):
    """Request model for saving a lot."""

    name: str
    card_ids: list[int]
    description: Optional[str] = None


class CardRead(CardBase):
    """Response model for card data."""

    id: int
    image_path: Optional[str] = Field(None, description="Local image path if stored")
    market_url: Optional[str] = Field(None, description="Listing/reference URL (e.g., PriceCharting)")
    language: Optional[str] = Field(None, description="Card language (e.g., English, Japanese)")
    created_at: datetime
    updated_at: datetime
    
    # Trend analysis fields
    flip_score: Optional[float] = Field(None, description="Static flip score")
    sma_30: Optional[float] = Field(None, description="30-day Simple Moving Average")
    ema_30: Optional[float] = Field(None, description="30-day Exponential Moving Average")
    trend_score_sma: Optional[float] = Field(None, description="SMA-based trend score")
    trend_score_ema: Optional[float] = Field(None, description="EMA-based trend score")
    
    # Supply/Demand fields (Golden Ratio)
    sales_volume_text: Optional[str] = Field(None, description="Raw sales volume text")
    sales_per_week: Optional[float] = Field(None, description="Normalized sales per week")
    active_listings: Optional[int] = Field(None, description="Number of active listings")
    price_change: Optional[float] = Field(None, description="Recent price change")
    supply_score: Optional[float] = Field(None, description="Calculated supply score (0-100)")
    demand_score: Optional[float] = Field(None, description="Calculated demand score (0-100)")
    golden_ratio_score: Optional[float] = Field(None, description="Golden ratio flip opportunity score")

    model_config = ConfigDict(from_attributes=True)


class CardListResponse(BaseModel):
    """Paginated card list response."""

    total: int
    items: list[CardRead]

