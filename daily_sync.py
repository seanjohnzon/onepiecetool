#!/usr/bin/env python3
"""
Daily Data Sync Scheduler

Runs daily at 6 AM EST to:
1. Sync prices from PriceCharting
2. Scrape market data (volume, listings, sales history)
3. Capture daily price snapshots for trend analysis
4. Recalculate all scores (golden ratio, flip score, trends)

Usage:
    # Run manually
    python daily_sync.py
    
    # Run as cron job (6 AM EST = 11 AM UTC)
    # Add to crontab: 0 11 * * * cd /path/to/project && /path/to/venv/bin/python daily_sync.py >> logs/daily_sync.log 2>&1
"""

import os
import sys
import time
import sqlite3
import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any

import httpx
from bs4 import BeautifulSoup

# Setup logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / f"sync_{date.today().isoformat()}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

DB_PATH = Path(__file__).parent / "data" / "cards.db"
RATE_LIMIT_SECONDS = 1.2  # Be nice to PriceCharting
BATCH_SIZE = 50
MAX_CARDS_PER_SYNC = 500  # Limit cards per daily sync (rotate through DB)


# =============================================================================
# PARSING HELPERS
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
    """Parse price string like '$1,234.56'."""
    if not price_str:
        return None
    cleaned = price_str.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_price_change(text: str) -> Optional[float]:
    """Parse price change like '+$120.37' or '-$50.00'."""
    if not text:
        return None
    text = text.replace(",", "").replace("$", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


# =============================================================================
# SCORE CALCULATIONS
# =============================================================================

def calculate_supply_score(active_listings: Optional[int], sales_per_week: Optional[float]) -> float:
    """Calculate supply score (0-100)."""
    if active_listings is None:
        if sales_per_week and sales_per_week >= 7:
            active_listings = 100
        elif sales_per_week and sales_per_week >= 3:
            active_listings = 50
        else:
            active_listings = 30
    
    if sales_per_week is None:
        sales_per_week = 1.0
    
    listings_score = max(0, 50 - (active_listings / 2))
    sales_score = min(50, sales_per_week * 3)
    return round(listings_score + sales_score, 2)


def calculate_demand_score(sales_per_week: Optional[float], price: Optional[float]) -> float:
    """Calculate demand score (0-100)."""
    if sales_per_week is None:
        sales_per_week = 0.5
    if price is None or price <= 0:
        price = 1.0
    
    base_score = min(50, sales_per_week * 7)
    
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
    price: float, rarity_score: float, supply_score: float, demand_score: float,
    character_name: str, variant: str, price_change: Optional[float] = None
) -> float:
    """Calculate golden ratio score for flip opportunity detection."""
    # Character tiers
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
        var_mult = 1.15
    elif "manga" in var_lower:
        var_mult = 0.7
    elif "alt" in var_lower or "alternate" in var_lower:
        var_mult = 1.08
    elif "wanted" in var_lower or "anniv" in var_lower:
        var_mult = 1.10
    elif "promo" in var_lower or "winner" in var_lower:
        var_mult = 1.05
    else:
        var_mult = 1.0
    
    # Price tier
    if 15 <= price <= 50:
        price_tier = 1.12
    elif 50 < price <= 150:
        price_tier = 1.08
    elif 150 < price <= 500:
        price_tier = 1.0
    elif price > 500:
        price_tier = 0.80
    else:
        price_tier = 0.90
    
    # Momentum
    if price_change and price > 0 and price_change > 0:
        momentum = 1 + min(0.08, price_change / price * 0.4)
    elif price_change and price > 0 and price_change < 0:
        momentum = max(0.92, 1 + price_change / price * 0.2)
    else:
        momentum = 1.0
    
    # Core formula
    base_score = (rarity_score * 0.35) + (supply_score * 0.20) + (demand_score * 0.25) + 20
    return round(base_score * char_mult * var_mult * price_tier * momentum, 2)


# =============================================================================
# SCRAPING & SYNC
# =============================================================================

def scrape_card_data(url: str) -> Dict[str, Any]:
    """Scrape price and market data from PriceCharting page."""
    result = {
        "price": None,
        "price_change": None,
        "sales_volume_text": None,
        "sales_per_week": None,
        "active_listings": None,
        "release_date": None,
        "recent_sales": [],
    }
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Get current price from price table
        price_cells = soup.find_all("td")
        for cell in price_cells:
            text = cell.get_text()
            if text.startswith("$") and "." in text:
                price = parse_price(text.split()[0])
                if price and price > 0:
                    result["price"] = price
                    break
        
        # Volume text
        for cell in soup.find_all("td"):
            text = cell.get_text()
            if "volume:" in text.lower():
                link = cell.find("a")
                if link:
                    vol_text = link.get_text(strip=True)
                    result["sales_volume_text"] = vol_text
                    result["sales_per_week"] = parse_sales_volume(vol_text)
                    break
        
        # Price change
        change_elem = soup.find(string=re.compile(r"[+-]\$[\d,]+\.\d{2}"))
        if change_elem:
            result["price_change"] = parse_price_change(str(change_elem))
        
        # Listings count
        listings_text = soup.find(string=re.compile(r"Ungraded \(\d+\)"))
        if listings_text:
            match = re.search(r'\((\d+)\)', listings_text)
            if match:
                result["active_listings"] = int(match.group(1))
        
        # Recent sales for price history
        sale_header = soup.find(string=re.compile(r"Sale Date"))
        if sale_header:
            table = sale_header.find_parent("table")
            if table:
                rows = table.find_all("tr")[1:11]  # First 10 sales
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 4:
                        try:
                            sale_date = datetime.strptime(cells[0].get_text(strip=True), "%Y-%m-%d").date()
                            sale_price = parse_price(cells[3].get_text(strip=True))
                            if sale_date and sale_price:
                                result["recent_sales"].append({"date": sale_date, "price": sale_price})
                        except (ValueError, AttributeError):
                            continue
    
    except Exception as e:
        logger.warning(f"Error scraping {url}: {e}")
    
    return result


def sync_card(cursor, card_id: int, card_name: str, variant: str, 
              rarity_score: float, market_url: str) -> bool:
    """Sync a single card's data from PriceCharting."""
    data = scrape_card_data(market_url)
    
    if not data["price"]:
        return False
    
    # Calculate scores
    supply = calculate_supply_score(data["active_listings"], data["sales_per_week"])
    demand = calculate_demand_score(data["sales_per_week"], data["price"])
    golden = calculate_golden_ratio_score(
        data["price"], rarity_score or 40, supply, demand,
        card_name, variant, data["price_change"]
    )
    
    # Update card
    cursor.execute("""
        UPDATE cards SET
            price = ?,
            sales_volume_text = ?,
            sales_per_week = ?,
            active_listings = ?,
            price_change = ?,
            supply_score = ?,
            demand_score = ?,
            golden_ratio_score = ?,
            last_checked = ?,
            last_market_sync = ?
        WHERE id = ?
    """, (
        data["price"],
        data["sales_volume_text"],
        data["sales_per_week"],
        data["active_listings"],
        data["price_change"],
        supply,
        demand,
        golden,
        date.today().isoformat(),
        datetime.now().isoformat(),
        card_id
    ))
    
    # Insert price history from recent sales (growing the database over time)
    for sale in data["recent_sales"]:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO price_history (card_id, price, recorded_at, source)
                VALUES (?, ?, ?, 'daily_sync')
            """, (card_id, sale["price"], sale["date"].isoformat()))
        except Exception:
            pass
    
    # Also capture today's price snapshot
    cursor.execute("""
        INSERT OR IGNORE INTO price_history (card_id, price, recorded_at, source)
        VALUES (?, ?, ?, 'daily_sync')
    """, (card_id, data["price"], date.today().isoformat()))
    
    return True


def run_daily_sync():
    """Main daily sync execution."""
    start_time = datetime.now()
    logger.info("=" * 70)
    logger.info("🌊 DAILY DATA SYNC STARTED")
    logger.info(f"   Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get cards to sync (rotate through DB - oldest synced first)
    # Prioritize high-value cards
    cursor.execute("""
        SELECT id, card_name, variant, rarity_score, market_url
        FROM cards
        WHERE market_url IS NOT NULL
          AND market_url != ''
          AND price > 0.50
        ORDER BY 
            CASE WHEN last_market_sync IS NULL THEN 0 ELSE 1 END,
            last_market_sync ASC,
            price DESC
        LIMIT ?
    """, (MAX_CARDS_PER_SYNC,))
    
    cards = cursor.fetchall()
    total = len(cards)
    
    logger.info(f"📊 Cards to sync: {total}")
    
    success = 0
    errors = 0
    
    for i, (card_id, card_name, variant, rarity, market_url) in enumerate(cards, 1):
        try:
            if sync_card(cursor, card_id, card_name, variant, rarity, market_url):
                success += 1
                if i % 50 == 0:
                    logger.info(f"   Progress: {i}/{total} ({success} synced)")
            else:
                errors += 1
            
            # Commit periodically
            if i % BATCH_SIZE == 0:
                conn.commit()
            
            time.sleep(RATE_LIMIT_SECONDS)
            
        except KeyboardInterrupt:
            logger.warning("Interrupted! Saving progress...")
            break
        except Exception as e:
            logger.error(f"Error syncing card {card_id}: {e}")
            errors += 1
    
    conn.commit()
    conn.close()
    
    # Summary
    elapsed = datetime.now() - start_time
    logger.info("=" * 70)
    logger.info("✅ DAILY SYNC COMPLETE")
    logger.info(f"   Cards synced: {success}")
    logger.info(f"   Errors: {errors}")
    logger.info(f"   Duration: {elapsed}")
    logger.info("=" * 70)
    
    return {"success": success, "errors": errors, "duration": str(elapsed)}


if __name__ == "__main__":
    run_daily_sync()
