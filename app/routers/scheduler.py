"""
Scheduled sync router for daily data updates.

Triggered by external cron service (cron-job.org, EasyCron, etc.)
or manually via the API.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from sqlalchemy.orm import Session
import httpx
from bs4 import BeautifulSoup

from ..database import get_db
from ..models import Card, PriceHistory

router = APIRouter(prefix="/sync", tags=["scheduler"])

# Secret token for cron authentication (set in Railway environment)
CRON_SECRET = os.getenv("CRON_SECRET", "change-me-in-production")
RATE_LIMIT = 1.2
MAX_CARDS_PER_SYNC = 200  # Limit per sync to avoid timeout


# =============================================================================
# HELPERS
# =============================================================================

def parse_sales_volume(volume_text: str) -> float:
    """Convert volume text to sales per week."""
    text = volume_text.lower().strip()
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    num = float(match.group(1)) if match else 1.0
    
    if "day" in text:
        return num * 7
    elif "week" in text:
        return num
    elif "month" in text:
        return num / 4.33
    elif "rare" in text or "year" in text:
        return 0.1
    return 0.5


def parse_price(price_str: str) -> Optional[float]:
    """Parse price string."""
    if not price_str:
        return None
    cleaned = price_str.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def calculate_supply_score(listings: Optional[int], spw: Optional[float]) -> float:
    """Calculate supply score."""
    if listings is None:
        listings = 50 if (spw and spw >= 3) else 30
    if spw is None:
        spw = 1.0
    return round(max(0, 50 - listings/2) + min(50, spw * 3), 2)


def calculate_demand_score(spw: Optional[float], price: Optional[float]) -> float:
    """Calculate demand score."""
    if spw is None:
        spw = 0.5
    if price is None or price <= 0:
        price = 1.0
    base = min(50, spw * 7)
    bonus = 0
    if price >= 100 and spw >= 1:
        bonus = min(30, (spw / 3) * 20)
    elif price >= 50 and spw >= 1:
        bonus = min(20, (spw / 3) * 15)
    return round(base + bonus, 2)


def calculate_golden_score(price, rarity, supply, demand, name, variant, pchange):
    """Calculate golden ratio score."""
    # Character multiplier
    char = name.lower()
    if "luffy" in char:
        cm = 1.12
    elif any(c in char for c in ["shanks", "zoro", "nami", "boa"]):
        cm = 1.08
    elif any(c in char for c in ["ace", "sabo", "law", "kaido"]):
        cm = 1.05
    else:
        cm = 1.0
    
    # Variant multiplier
    var = (variant or "").lower()
    if "sp" in var and "leader" not in var:
        vm = 1.15
    elif "manga" in var:
        vm = 0.7
    elif "alt" in var:
        vm = 1.08
    elif "wanted" in var or "anniv" in var:
        vm = 1.10
    else:
        vm = 1.0
    
    # Price tier
    if 15 <= price <= 50:
        pt = 1.12
    elif 50 < price <= 150:
        pt = 1.08
    elif price > 500:
        pt = 0.80
    elif price < 5:
        pt = 0.90
    else:
        pt = 1.0
    
    # Momentum
    if pchange and pchange > 0:
        mom = 1 + min(0.08, pchange / price * 0.4) if price > 0 else 1.0
    elif pchange and pchange < 0:
        mom = max(0.92, 1 + pchange / price * 0.2) if price > 0 else 1.0
    else:
        mom = 1.0
    
    base = (rarity * 0.35) + (supply * 0.20) + (demand * 0.25) + 20
    return round(base * cm * vm * pt * mom, 2)


def scrape_and_update_card(db: Session, card: Card) -> bool:
    """Scrape and update a single card."""
    if not card.market_url:
        return False
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
        resp = httpx.get(card.market_url, headers=headers, timeout=20, follow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Get price
        new_price = None
        for cell in soup.find_all("td"):
            text = cell.get_text()
            if text.startswith("$"):
                p = parse_price(text.split()[0])
                if p and p > 0:
                    new_price = p
                    break
        
        if not new_price:
            return False
        
        # Volume
        spw = None
        vol_text = None
        for cell in soup.find_all("td"):
            if "volume:" in cell.get_text().lower():
                link = cell.find("a")
                if link:
                    vol_text = link.get_text(strip=True)
                    spw = parse_sales_volume(vol_text)
                    break
        
        # Listings
        listings = None
        lt = soup.find(string=re.compile(r"Ungraded \(\d+\)"))
        if lt:
            m = re.search(r'\((\d+)\)', lt)
            if m:
                listings = int(m.group(1))
        
        # Price change
        pchange = None
        pc_el = soup.find(string=re.compile(r"[+-]\$[\d,]+\.\d{2}"))
        if pc_el:
            pchange = parse_price(str(pc_el).replace("+", ""))
        
        # Calculate scores
        rarity = card.rarity_score or 40
        supply = calculate_supply_score(listings, spw)
        demand = calculate_demand_score(spw, new_price)
        golden = calculate_golden_score(new_price, rarity, supply, demand, 
                                        card.card_name, card.variant, pchange)
        
        # Update card
        card.price = new_price
        card.sales_volume_text = vol_text
        card.sales_per_week = spw
        card.active_listings = listings
        card.price_change = pchange
        card.supply_score = supply
        card.demand_score = demand
        card.golden_ratio_score = golden
        card.last_checked = date.today()
        card.last_market_sync = datetime.now()
        
        # Add price history
        existing = db.query(PriceHistory).filter(
            PriceHistory.card_id == card.id,
            PriceHistory.recorded_at == date.today()
        ).first()
        
        if not existing:
            db.add(PriceHistory(
                card_id=card.id,
                price=new_price,
                recorded_at=date.today(),
                source="scheduled_sync"
            ))
        
        return True
        
    except Exception as e:
        print(f"Error syncing {card.card_name}: {e}")
        return False


def run_sync_batch(db: Session, limit: int = MAX_CARDS_PER_SYNC) -> dict:
    """Run sync on a batch of cards."""
    # Get oldest synced cards first
    cards = db.query(Card).filter(
        Card.market_url.isnot(None),
        Card.price > 0.5
    ).order_by(
        Card.last_market_sync.asc().nullsfirst()
    ).limit(limit).all()
    
    success = 0
    errors = 0
    
    for card in cards:
        if scrape_and_update_card(db, card):
            success += 1
        else:
            errors += 1
        
        if success % 20 == 0:
            db.commit()  # Periodic commit
        
        time.sleep(RATE_LIMIT)
    
    db.commit()
    
    return {
        "success": success,
        "errors": errors,
        "total_attempted": len(cards),
        "timestamp": datetime.now().isoformat()
    }


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.post("/daily")
async def trigger_daily_sync(
    background_tasks: BackgroundTasks,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """
    Trigger daily sync. Protected by CRON_SECRET.
    
    Call from external cron service with header:
    Authorization: Bearer <CRON_SECRET>
    """
    # Verify secret
    expected = f"Bearer {CRON_SECRET}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid authorization")
    
    # Run sync in background to avoid timeout
    background_tasks.add_task(run_sync_batch, db)
    
    return {
        "status": "started",
        "message": f"Daily sync started for up to {MAX_CARDS_PER_SYNC} cards",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/status")
async def sync_status(db: Session = Depends(get_db)):
    """Get sync status and database stats."""
    
    # Count records
    total_cards = db.query(Card).count()
    synced_today = db.query(Card).filter(
        Card.last_market_sync >= datetime.now().replace(hour=0, minute=0)
    ).count()
    history_count = db.query(PriceHistory).count()
    
    # Get last sync time
    last_synced = db.query(Card.last_market_sync).filter(
        Card.last_market_sync.isnot(None)
    ).order_by(Card.last_market_sync.desc()).first()
    
    return {
        "total_cards": total_cards,
        "synced_today": synced_today,
        "price_history_records": history_count,
        "last_sync": last_synced[0].isoformat() if last_synced and last_synced[0] else None
    }


@router.post("/manual")
async def manual_sync(
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Run a manual sync (for testing). Limited to 50 cards.
    """
    if limit > 50:
        limit = 50
    
    result = run_sync_batch(db, limit)
    return result
