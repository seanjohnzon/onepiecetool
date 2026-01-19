"""
Trend calculation service for price analysis.

Handles:
- Daily price snapshots
- SMA (Simple Moving Average) calculation
- EMA (Exponential Moving Average) calculation
- Trend score computation
- Total score (static flip + trend)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Card, PriceHistory, CalcConfig


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_config(db: Session, key: str, default: float = 0.0) -> float:
    """
    Get a configuration value.

    Args:
        db: Database session.
        key: Configuration key.
        default: Default value if not found.

    Returns:
        Configuration value as float.
    """
    config = db.query(CalcConfig).filter(CalcConfig.key == key).first()
    return config.value if config else default


def get_all_config(db: Session) -> dict[str, float]:
    """
    Get all configuration values as a dictionary.

    Args:
        db: Database session.

    Returns:
        Dictionary of key -> value.
    """
    configs = db.query(CalcConfig).all()
    return {c.key: c.value for c in configs}


def update_config(
    db: Session,
    key: str,
    new_value: float,
    reason: Optional[str] = None
) -> bool:
    """
    Update a configuration value with audit logging.

    Args:
        db: Database session.
        key: Configuration key.
        new_value: New value.
        reason: Optional reason for change.

    Returns:
        True if updated, False if key not found.
    """
    config = db.query(CalcConfig).filter(CalcConfig.key == key).first()
    if not config:
        return False

    old_value = config.value

    # Check bounds
    if config.min_bound is not None and new_value < config.min_bound:
        new_value = config.min_bound
    if config.max_bound is not None and new_value > config.max_bound:
        new_value = config.max_bound

    # Log the change
    db.execute(
        text("""
            INSERT INTO config_log (config_key, old_value, new_value, reason)
            VALUES (:key, :old, :new, :reason)
        """),
        {"key": key, "old": old_value, "new": new_value, "reason": reason}
    )

    config.value = new_value
    db.commit()
    return True


# =============================================================================
# PRICE SNAPSHOTS
# =============================================================================

def capture_daily_prices(db: Session) -> dict:
    """
    Capture current prices for all cards as daily snapshot.

    Only captures one snapshot per card per day (uses UPSERT logic).

    Args:
        db: Database session.

    Returns:
        Dictionary with captured/skipped counts.
    """
    today = date.today()
    captured = 0
    skipped = 0

    # Get all cards with valid prices
    cards = db.query(Card).filter(
        Card.price.isnot(None),
        Card.price > 0
    ).all()

    for card in cards:
        # Check if we already have a snapshot for today
        existing = db.execute(
            text("""
                SELECT id FROM price_history
                WHERE card_id = :card_id AND recorded_at = :today
            """),
            {"card_id": card.id, "today": today}
        ).fetchone()

        if existing:
            skipped += 1
            continue

        # Insert new snapshot
        db.execute(
            text("""
                INSERT INTO price_history (card_id, price, recorded_at, source)
                VALUES (:card_id, :price, :today, 'pricecharting')
            """),
            {"card_id": card.id, "price": card.price, "today": today}
        )
        captured += 1

    db.commit()
    return {"captured": captured, "skipped": skipped, "date": str(today)}


def get_price_history(db: Session, card_id: int, limit: int = 30) -> list[dict]:
    """
    Get price history for a card.

    Args:
        db: Database session.
        card_id: Card ID.
        limit: Maximum number of data points to retrieve (most recent first, then reversed).

    Returns:
        List of {date, price} dictionaries ordered oldest to newest.
    """
    # Get most recent N data points (works with monthly or daily data)
    rows = db.execute(
        text("""
            SELECT recorded_at, price
            FROM price_history
            WHERE card_id = :card_id
            ORDER BY recorded_at DESC
            LIMIT :limit
        """),
        {"card_id": card_id, "limit": limit}
    ).fetchall()

    # Reverse to get oldest first (needed for SMA/EMA calculation)
    return [{"date": str(r[0]), "price": r[1]} for r in reversed(rows)]


# =============================================================================
# MOVING AVERAGE CALCULATIONS
# =============================================================================

def calculate_sma(prices: list[float], period: int) -> Optional[float]:
    """
    Calculate Simple Moving Average.

    Args:
        prices: List of prices (oldest first).
        period: Number of periods.

    Returns:
        SMA value or None if insufficient data.
    """
    if len(prices) < period:
        return None
    recent = prices[-period:]
    return sum(recent) / len(recent)


def calculate_ema(prices: list[float], period: int, smoothing: float = 2.0) -> Optional[float]:
    """
    Calculate Exponential Moving Average.

    Args:
        prices: List of prices (oldest first).
        period: Number of periods.
        smoothing: Smoothing factor (default 2.0).

    Returns:
        EMA value or None if insufficient data.
    """
    if len(prices) < period:
        return None

    # Start with SMA of first `period` prices
    k = smoothing / (period + 1)
    ema = sum(prices[:period]) / period

    # Apply EMA formula for remaining prices
    for price in prices[period:]:
        ema = (price * k) + (ema * (1 - k))

    return ema


def calculate_trend_score(
    current_price: float,
    moving_avg: float,
    trend_cap: float = 50.0
) -> float:
    """
    Calculate trend score based on price deviation from moving average.

    Positive score = price above average (uptrend)
    Negative score = price below average (downtrend)

    Args:
        current_price: Current card price.
        moving_avg: Moving average value.
        trend_cap: Maximum absolute score.

    Returns:
        Trend score (-cap to +cap).
    """
    if moving_avg <= 0:
        return 0.0

    # Percentage deviation
    deviation_pct = ((current_price - moving_avg) / moving_avg) * 100

    # Scale and cap
    trend_score = deviation_pct
    trend_score = max(-trend_cap, min(trend_cap, trend_score))

    return round(trend_score, 2)


# =============================================================================
# TREND UPDATES FOR CARDS
# =============================================================================

def update_card_trends(db: Session, card: Card) -> dict:
    """
    Calculate and update SMA/EMA trends for a single card.

    Args:
        db: Database session.
        card: Card to update.

    Returns:
        Dictionary with calculation results.
    """
    config = get_all_config(db)

    sma_period = int(config.get("sma_period", 30))
    ema_period = int(config.get("ema_period", 30))
    ema_smoothing = config.get("ema_smoothing", 2.0)
    trend_cap = config.get("trend_cap", 50.0)
    sma_weight = config.get("sma_weight", 0.5)
    ema_weight = config.get("ema_weight", 0.5)
    min_history = int(config.get("min_history_days", 7))

    # Get price history (limit to enough data points for calculation)
    history = get_price_history(db, card.id, limit=max(sma_period, ema_period) + 10)
    prices = [h["price"] for h in history]

    result = {
        "card_id": card.id,
        "history_days": len(prices),
        "sma_30": None,
        "ema_30": None,
        "trend_score_sma": None,
        "trend_score_ema": None,
        "total_score_sma": None,
        "total_score_ema": None,
    }

    if len(prices) < min_history:
        return result

    # Calculate SMA
    sma = calculate_sma(prices, sma_period)
    if sma:
        card.sma_30 = round(sma, 2)
        trend_sma = calculate_trend_score(card.price, sma, trend_cap)
        card.trend_score_sma = trend_sma
        result["sma_30"] = card.sma_30
        result["trend_score_sma"] = trend_sma

        # Total score = flip_score + weighted trend
        if card.flip_score is not None:
            card.total_score_sma = round(
                card.flip_score + (trend_sma * sma_weight), 2
            )
            result["total_score_sma"] = card.total_score_sma

    # Calculate EMA
    ema = calculate_ema(prices, ema_period, ema_smoothing)
    if ema:
        card.ema_30 = round(ema, 2)
        trend_ema = calculate_trend_score(card.price, ema, trend_cap)
        card.trend_score_ema = trend_ema
        result["ema_30"] = card.ema_30
        result["trend_score_ema"] = trend_ema

        # Total score = flip_score + weighted trend
        if card.flip_score is not None:
            card.total_score_ema = round(
                card.flip_score + (trend_ema * ema_weight), 2
            )
            result["total_score_ema"] = card.total_score_ema

    card.last_trend_calc = date.today()
    db.commit()

    return result


def update_all_trends(db: Session) -> dict:
    """
    Update trends for all cards with sufficient price history.

    Args:
        db: Database session.

    Returns:
        Summary statistics.
    """
    config = get_all_config(db)
    min_history = int(config.get("min_history_days", 7))

    # Find cards with enough history
    cards_with_history = db.execute(
        text("""
            SELECT c.id
            FROM cards c
            JOIN price_history ph ON c.id = ph.card_id
            WHERE c.price > 0
            GROUP BY c.id
            HAVING COUNT(ph.id) >= :min_history
        """),
        {"min_history": min_history}
    ).fetchall()

    card_ids = [r[0] for r in cards_with_history]

    updated = 0
    skipped = 0

    for card_id in card_ids:
        card = db.get(Card, card_id)
        if card:
            result = update_card_trends(db, card)
            if result.get("sma_30") or result.get("ema_30"):
                updated += 1
            else:
                skipped += 1

    return {
        "updated": updated,
        "skipped": skipped,
        "total_eligible": len(card_ids),
    }


# =============================================================================
# FLIP SCORE CALCULATION
# =============================================================================

def calculate_flip_score(
    card: Card,
    char_avg: float,
    config: dict
) -> Optional[float]:
    """
    Calculate static flip score for a card.

    Formula: (Discount %) × √(Adjusted Char Avg) / 10 × Price Bonus

    Args:
        card: Card to score.
        char_avg: Average price of same character's other variants.
        config: Configuration dictionary.

    Returns:
        Flip score or None if not calculable.
    """
    if not card.price or card.price <= 0 or char_avg <= 0:
        return None

    # Discount percentage (how much below average)
    discount_pct = (1 - card.price / char_avg) * 100

    # Sqrt scaling for character value
    sqrt_char = (char_avg ** 0.5) / 10

    # Price bonus
    sweet_low = config.get("sweet_low", 15)
    sweet_high = config.get("sweet_high", 100)
    mid_low = config.get("mid_low", 100)
    mid_high = config.get("mid_high", 500)
    sweet_bonus = config.get("sweet_bonus", 1.2)
    mid_bonus = config.get("mid_bonus", 1.0)
    high_bonus = config.get("high_bonus", 0.8)
    low_bonus = config.get("low_bonus", 0.9)

    if sweet_low <= card.price <= sweet_high:
        price_bonus = sweet_bonus
    elif mid_low <= card.price <= mid_high:
        price_bonus = mid_bonus
    elif card.price > mid_high:
        price_bonus = high_bonus
    else:
        price_bonus = low_bonus

    flip_score = discount_pct * sqrt_char * price_bonus

    return round(flip_score, 2)


def update_all_flip_scores(db: Session) -> dict:
    """
    Calculate and update flip scores for all eligible cards.

    Args:
        db: Database session.

    Returns:
        Summary statistics.
    """
    config = get_all_config(db)
    min_variants = int(config.get("min_variants", 4))
    min_char_avg = config.get("min_char_avg", 30)
    min_price = config.get("min_price", 10)

    # Get character averages (excluding top variant per character)
    char_stats = db.execute(
        text("""
            WITH ranked AS (
                SELECT card_name, price,
                    ROW_NUMBER() OVER (PARTITION BY card_name ORDER BY price DESC) as price_rank
                FROM cards
                WHERE price >= :min_price
                    AND card_name NOT LIKE '%Booster%'
                    AND card_name NOT LIKE '%Box%'
                    AND (variant NOT LIKE '%Deck%Foil%' OR variant IS NULL)
            )
            SELECT card_name,
                AVG(CASE WHEN price_rank > 1 THEN price END) as adjusted_avg,
                COUNT(*) as variant_count
            FROM ranked
            GROUP BY card_name
            HAVING COUNT(*) >= :min_variants
                AND AVG(CASE WHEN price_rank > 1 THEN price END) >= :min_char_avg
        """),
        {"min_price": min_price, "min_variants": min_variants, "min_char_avg": min_char_avg}
    ).fetchall()

    char_avgs = {r[0]: r[1] for r in char_stats}

    updated = 0
    skipped = 0

    for card_name, avg in char_avgs.items():
        cards = db.query(Card).filter(
            Card.card_name == card_name,
            Card.price >= min_price
        ).all()

        for card in cards:
            flip_score = calculate_flip_score(card, avg, config)
            if flip_score is not None:
                card.flip_score = flip_score
                updated += 1
            else:
                skipped += 1

    db.commit()
    return {"updated": updated, "skipped": skipped, "characters": len(char_avgs)}


# =============================================================================
# GOLDEN RATIO FORMULA (Supply/Demand Based)
# =============================================================================

def calculate_supply_score(active_listings: Optional[int], sales_per_week: Optional[float]) -> float:
    """
    Calculate supply score (0-100) based on listings and sales velocity.
    
    Low listings + high sales = scarce (high score)
    High listings + low sales = abundant (low score)
    
    Args:
        active_listings: Number of cards listed for sale.
        sales_per_week: Normalized sales per week.
    
    Returns:
        Supply score (0-100).
    """
    if active_listings is None:
        # Without listing data, use sales frequency as proxy
        if sales_per_week and sales_per_week >= 7:
            active_listings = 100  # High sales = probably abundant
        elif sales_per_week and sales_per_week >= 3:
            active_listings = 50
        else:
            active_listings = 30
    
    if sales_per_week is None:
        sales_per_week = 1.0
    
    # Fewer listings = higher score (scarcer)
    listings_score = max(0, 50 - (active_listings / 2))
    
    # More sales = selling out faster = scarcer
    sales_score = min(50, sales_per_week * 3)
    
    return round(listings_score + sales_score, 2)


def calculate_demand_score(sales_per_week: Optional[float], price: Optional[float]) -> float:
    """
    Calculate demand score (0-100) based on sales velocity and price.
    
    High sales + higher price = strong demand
    Low sales + low price = weak demand
    
    Args:
        sales_per_week: Normalized sales per week.
        price: Current card price.
    
    Returns:
        Demand score (0-100).
    """
    if sales_per_week is None:
        sales_per_week = 0.5
    if price is None or price <= 0:
        price = 1.0
    
    # Base: sales per week (0-50)
    base_score = min(50, sales_per_week * 7)
    
    # Price bonus for expensive cards with actual sales
    if price >= 100 and sales_per_week >= 1:
        price_bonus = min(30, (sales_per_week / 3) * 20)
    elif price >= 50 and sales_per_week >= 1:
        price_bonus = min(20, (sales_per_week / 3) * 15)
    elif price >= 20 and sales_per_week >= 1:
        price_bonus = min(10, (sales_per_week / 3) * 10)
    else:
        price_bonus = 0
    
    return round(base_score + price_bonus, 2)


def calculate_golden_ratio_score(
    price: float,
    rarity_score: float,
    supply_score: float,
    demand_score: float,
    character_name: str,
    variant: Optional[str] = None,
    price_change: Optional[float] = None
) -> float:
    """
    Calculate the Golden Ratio score for flip opportunity detection.
    
    Combines rarity, supply/demand, character premium, variant type,
    and price tier to find undervalued cards with good flip potential.
    
    Args:
        price: Current card price.
        rarity_score: Rarity score (0-100).
        supply_score: Supply score (0-100).
        demand_score: Demand score (0-100).
        character_name: Character name for premium calculation.
        variant: Variant type for type multiplier.
        price_change: Recent price movement.
    
    Returns:
        Golden ratio score (higher = better flip opportunity).
    """
    # Character tiers (popularity multiplier)
    char_lower = character_name.lower()
    if any(c in char_lower for c in ["luffy", "monkey.d.luffy"]):
        char_mult = 1.12
    elif any(c in char_lower for c in ["shanks", "zoro", "roronoa", "nami", "boa hancock"]):
        char_mult = 1.08
    elif any(c in char_lower for c in ["ace", "sabo", "law", "trafalgar", "kaido", "big mom"]):
        char_mult = 1.05
    elif any(c in char_lower for c in ["sanji", "robin", "chopper", "yamato", "uta"]):
        char_mult = 1.03
    else:
        char_mult = 1.0
    
    # Variant type multiplier
    var_lower = (variant or "").lower()
    if "sp" in var_lower and "leader" not in var_lower:
        var_mult = 1.15  # SP cards get bonus
    elif "manga" in var_lower:
        var_mult = 0.7   # Manga cards penalized (controversial, volatile)
    elif "alt" in var_lower or "alternate" in var_lower:
        var_mult = 1.08
    elif "wanted" in var_lower or "anniv" in var_lower:
        var_mult = 1.10
    elif "promo" in var_lower or "winner" in var_lower:
        var_mult = 1.05
    else:
        var_mult = 1.0  # Base/common
    
    # Price tier bonus (sweet spot detection)
    if 15 <= price <= 50:
        price_tier = 1.12  # Best flip range
    elif 50 < price <= 150:
        price_tier = 1.08  # Good flip range
    elif 150 < price <= 500:
        price_tier = 1.0   # Moderate
    elif price > 500:
        price_tier = 0.80  # Liquidity penalty
    else:
        price_tier = 0.90  # Too cheap
    
    # Momentum bonus
    if price_change and price > 0 and price_change > 0:
        momentum = 1 + min(0.08, price_change / price * 0.4)
    elif price_change and price > 0 and price_change < 0:
        momentum = max(0.92, 1 + price_change / price * 0.2)
    else:
        momentum = 1.0
    
    # Core formula
    # Weights: Rarity 35%, Supply 20%, Demand 25%, Base 20%
    base_score = (
        (rarity_score * 0.35) +
        (supply_score * 0.20) +
        (demand_score * 0.25) +
        (20)  # Base floor
    )
    
    # Apply all multipliers
    final_score = base_score * char_mult * var_mult * price_tier * momentum
    
    return round(final_score, 2)


def update_golden_ratio_scores(db: Session) -> dict:
    """
    Update golden ratio scores for all cards.
    
    Args:
        db: Database session.
    
    Returns:
        Summary statistics.
    """
    cards = db.query(Card).filter(Card.price > 0).all()
    
    updated = 0
    skipped = 0
    
    for card in cards:
        rarity = card.rarity_score if card.rarity_score else 40
        
        supply = calculate_supply_score(card.active_listings, card.sales_per_week)
        demand = calculate_demand_score(card.sales_per_week, card.price)
        golden = calculate_golden_ratio_score(
            price=card.price,
            rarity_score=rarity,
            supply_score=supply,
            demand_score=demand,
            character_name=card.card_name,
            variant=card.variant,
            price_change=card.price_change
        )
        
        card.supply_score = supply
        card.demand_score = demand
        card.golden_ratio_score = golden
        updated += 1
    
    db.commit()
    return {"updated": updated, "skipped": skipped}
