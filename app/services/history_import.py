"""
Import historical price data from PriceCharting chart_data.
"""

import re
import json
from datetime import datetime, date
from typing import Optional
import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Card


def extract_chart_data(html: str) -> Optional[dict]:
    """
    Extract VGPC.chart_data from PriceCharting HTML page.
    
    Returns dict with keys: boxonly, cib, graded, manualonly, new, used
    Each contains [[timestamp_ms, price_cents], ...]
    """
    match = re.search(r'VGPC\.chart_data\s*=\s*(\{[^;]+\});', html)
    if not match:
        return None
    
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def fetch_price_history(market_url: str, timeout: float = 15.0) -> list[dict]:
    """
    Fetch historical price data from a PriceCharting URL.
    
    Returns list of {date: str, price: float} for past 90+ days.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    try:
        resp = httpx.get(market_url, timeout=timeout, headers=headers, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"Error fetching {market_url}: {e}")
        return []
    
    chart_data = extract_chart_data(resp.text)
    if not chart_data:
        return []
    
    # Use "used" (Loose price) which is most relevant for cards
    used_data = chart_data.get("used", [])
    
    history = []
    for timestamp_ms, price_cents in used_data:
        if price_cents and price_cents > 0:
            # Convert timestamp to date
            dt = datetime.fromtimestamp(timestamp_ms / 1000)
            # Convert cents to dollars
            price = price_cents / 100.0
            history.append({
                "date": dt.date(),
                "price": price
            })
    
    return history


def import_history_for_card(db: Session, card: Card) -> dict:
    """
    Import historical prices for a single card.
    
    Args:
        db: Database session.
        card: Card to import history for.
        
    Returns:
        Dict with imported count and stats.
    """
    if not card.market_url:
        return {"card_id": card.id, "status": "no_url", "imported": 0}
    
    history = fetch_price_history(card.market_url)
    if not history:
        return {"card_id": card.id, "status": "no_data", "imported": 0}
    
    imported = 0
    for entry in history:
        # Check if already exists
        existing = db.execute(
            text("""
                SELECT id FROM price_history
                WHERE card_id = :card_id AND recorded_at = :date
            """),
            {"card_id": card.id, "date": entry["date"]}
        ).fetchone()
        
        if not existing:
            db.execute(
                text("""
                    INSERT INTO price_history (card_id, price, recorded_at, source)
                    VALUES (:card_id, :price, :date, 'pricecharting_historical')
                """),
                {
                    "card_id": card.id,
                    "price": entry["price"],
                    "date": entry["date"]
                }
            )
            imported += 1
    
    db.commit()
    return {
        "card_id": card.id,
        "card_name": card.card_name,
        "status": "success",
        "imported": imported,
        "total_history": len(history)
    }


def import_history_bulk(
    db: Session,
    limit: int = 100,
    min_price: float = 10.0,
    delay_seconds: float = 1.0
) -> dict:
    """
    Import historical prices for multiple high-value cards.
    
    Args:
        db: Database session.
        limit: Max cards to process.
        min_price: Only process cards above this price.
        delay_seconds: Delay between requests.
        
    Returns:
        Summary statistics.
    """
    import time
    
    # Get cards with market_url, ordered by price (high value first)
    cards = db.query(Card).filter(
        Card.market_url.isnot(None),
        Card.market_url != "",
        Card.price >= min_price
    ).order_by(Card.price.desc()).limit(limit).all()
    
    results = {
        "total_cards": len(cards),
        "successful": 0,
        "failed": 0,
        "total_imported": 0,
        "details": []
    }
    
    for i, card in enumerate(cards):
        print(f"[{i+1}/{len(cards)}] Processing {card.card_name} ({card.card_number})...")
        
        result = import_history_for_card(db, card)
        results["details"].append(result)
        
        if result["status"] == "success":
            results["successful"] += 1
            results["total_imported"] += result["imported"]
        else:
            results["failed"] += 1
        
        # Rate limiting
        if i < len(cards) - 1:
            time.sleep(delay_seconds)
    
    return results
