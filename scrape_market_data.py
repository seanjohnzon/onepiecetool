"""
PriceCharting Market Data Scraper

Scrapes supply/demand data from PriceCharting pages:
- Sales volume (demand signal)
- Active listings (supply signal)
- Price change (momentum)
- Release date (set age)
- Recent sales history (price history backfill)

Updates the database with calculated supply_score, demand_score, and golden_ratio_score.
"""

import sqlite3
import time
import re
from datetime import datetime, date
from typing import Optional, Dict, Any, List
import httpx
from bs4 import BeautifulSoup


# =============================================================================
# CONFIGURATION
# =============================================================================

DB_PATH = "data/cards.db"
RATE_LIMIT_SECONDS = 1.5  # Be nice to PriceCharting
BATCH_SIZE = 50  # Commit every N cards
MAX_RETRIES = 3


# =============================================================================
# PARSING HELPERS
# =============================================================================

def parse_sales_volume(volume_text: str) -> float:
    """
    Convert volume text to sales per week.
    
    Examples:
        "3 sales per week" -> 3.0
        "1 sale per day" -> 7.0
        "2 sales per month" -> 0.5
        "rare" -> 0.1
    """
    text = volume_text.lower().strip()
    
    # Extract number
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    num = float(match.group(1)) if match else 1.0
    
    if "day" in text:
        return num * 7  # Convert to weekly
    elif "week" in text:
        return num
    elif "month" in text:
        return num / 4.33  # Approx weeks per month
    elif "rare" in text:
        return 0.1  # Very low demand
    else:
        return 0.5  # Default to low


def parse_price_change(text: str) -> Optional[float]:
    """
    Parse price change like "+$120.37" or "-$50.00".
    """
    if not text:
        return None
    text = text.replace(",", "").replace("$", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_listings_count(text: str) -> Optional[int]:
    """
    Extract number from "Ungraded (51)".
    """
    match = re.search(r'\((\d+)\)', text)
    return int(match.group(1)) if match else None


def parse_release_date(text: str) -> Optional[date]:
    """
    Parse date like "June 28, 2024".
    """
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").date()
    except ValueError:
        return None


# =============================================================================
# SCORE CALCULATIONS
# =============================================================================

def calculate_supply_score(active_listings: Optional[int], sales_per_week: Optional[float]) -> float:
    """
    Calculate supply score (0-100).
    
    Low listings + high sales = scarce (high score)
    High listings + low sales = abundant (low score)
    
    Formula: 100 - (listings / max_listings * 50) + (sales_per_week / max_sales * 50)
    """
    if active_listings is None:
        active_listings = 50  # Assume moderate supply
    if sales_per_week is None:
        sales_per_week = 1.0  # Assume low demand
    
    # Normalize listings (0-100 range, capped)
    listings_score = max(0, 50 - (active_listings / 2))  # Fewer listings = higher score
    
    # Normalize sales (0-50 range)
    sales_score = min(50, sales_per_week * 5)  # More sales = selling out faster = scarcer
    
    return round(listings_score + sales_score, 2)


def calculate_demand_score(sales_per_week: Optional[float], price: Optional[float]) -> float:
    """
    Calculate demand score (0-100).
    
    High sales + higher price = strong demand
    Low sales + low price = weak demand
    
    Expensive cards selling multiple times per week = very high demand.
    """
    if sales_per_week is None:
        sales_per_week = 0.5
    if price is None or price <= 0:
        price = 1.0
    
    # Base: sales per week (0-70)
    base_score = min(70, sales_per_week * 10)
    
    # Price bonus: expensive cards with good sales = premium demand (0-30)
    if price >= 100:
        price_bonus = min(30, (sales_per_week / 3) * 30)
    elif price >= 50:
        price_bonus = min(20, (sales_per_week / 3) * 20)
    elif price >= 20:
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
    price_change: Optional[float] = None
) -> float:
    """
    The Golden Ratio formula for finding undervalued flip opportunities.
    
    Combines:
    - Rarity (variant type value)
    - Supply/Demand (market dynamics)
    - Character premium (Luffy, Shanks, etc.)
    - Price tier bonus (sweet spot detection)
    - Momentum (price change)
    """
    
    # Character tiers (popularity multiplier)
    char_lower = character_name.lower()
    if any(c in char_lower for c in ["luffy", "monkey.d.luffy"]):
        char_mult = 1.25
    elif any(c in char_lower for c in ["shanks", "zoro", "roronoa", "nami", "boa hancock"]):
        char_mult = 1.15
    elif any(c in char_lower for c in ["ace", "sabo", "law", "trafalgar", "kaido", "big mom"]):
        char_mult = 1.10
    elif any(c in char_lower for c in ["sanji", "robin", "chopper", "yamato", "uta"]):
        char_mult = 1.05
    else:
        char_mult = 1.0
    
    # Price tier bonus (sweet spot: $15-150 range)
    if 15 <= price <= 50:
        price_tier = 1.15  # Best flip range
    elif 50 < price <= 150:
        price_tier = 1.10  # Good flip range
    elif 150 < price <= 500:
        price_tier = 1.0   # Moderate
    elif price > 500:
        price_tier = 0.85  # Liquidity penalty
    else:
        price_tier = 0.95  # Too cheap
    
    # Momentum bonus (price going up = good)
    if price_change and price_change > 0:
        momentum = 1 + min(0.10, price_change / price * 0.5)  # Up to 10% bonus
    elif price_change and price_change < 0:
        momentum = max(0.90, 1 + price_change / price * 0.25)  # Slight penalty
    else:
        momentum = 1.0
    
    # Core formula
    # Weights: Rarity 25%, Supply 25%, Demand 30%, Base 20%
    base_score = (
        (rarity_score * 0.25) +
        (supply_score * 0.25) +
        (demand_score * 0.30) +
        (20)  # Base floor
    )
    
    # Apply multipliers
    final_score = base_score * char_mult * price_tier * momentum
    
    return round(final_score, 2)


# =============================================================================
# SCRAPING
# =============================================================================

def scrape_card_market_data(url: str) -> Dict[str, Any]:
    """
    Scrape market data from a PriceCharting card page.
    
    Returns dict with:
        - sales_volume_text
        - sales_per_week
        - active_listings
        - price_change
        - release_date
        - recent_sales (list of {date, price})
    """
    result = {
        "sales_volume_text": None,
        "sales_per_week": None,
        "active_listings": None,
        "price_change": None,
        "release_date": None,
        "recent_sales": [],
    }
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 1. Find volume text (e.g., "volume: 3 sales per week")
        volume_cells = soup.find_all(string=re.compile(r"volume:", re.I))
        for cell in volume_cells:
            parent = cell.find_parent("td")
            if parent:
                vol_link = parent.find("a")
                if vol_link:
                    vol_text = vol_link.get_text(strip=True)
                    result["sales_volume_text"] = vol_text
                    result["sales_per_week"] = parse_sales_volume(vol_text)
                    break
        
        # 2. Find active listings count from "Ungraded (51)"
        compare_section = soup.find(string=re.compile(r"Compare Prices"))
        if compare_section:
            parent = compare_section.find_parent("div")
            if parent:
                ungraded = parent.find(string=re.compile(r"Ungraded \(\d+\)"))
                if ungraded:
                    result["active_listings"] = parse_listings_count(ungraded)
        
        # 3. Find price change (dollar change from last update)
        price_change_el = soup.find("span", class_=re.compile(r"dollar.*change|change", re.I))
        if not price_change_el:
            price_change_el = soup.find(string=re.compile(r"[+-]\$[\d,]+\.\d{2}"))
        if price_change_el:
            text = price_change_el.get_text(strip=True) if hasattr(price_change_el, 'get_text') else str(price_change_el)
            result["price_change"] = parse_price_change(text)
        
        # 4. Find release date from details table
        release_row = soup.find("td", string=re.compile(r"Release Date:"))
        if release_row:
            next_cell = release_row.find_next_sibling("td")
            if next_cell:
                result["release_date"] = parse_release_date(next_cell.get_text())
        
        # 5. Scrape recent sales from sales table
        sales_table = soup.find("table", class_=re.compile(r"sales|history", re.I))
        if not sales_table:
            # Try finding by Sale Date header
            sale_date_header = soup.find(string=re.compile(r"Sale Date"))
            if sale_date_header:
                sales_table = sale_date_header.find_parent("table")
        
        if sales_table:
            rows = sales_table.find_all("tr")[1:21]  # Skip header, get up to 20 sales
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 4:
                    date_text = cells[0].get_text(strip=True)
                    price_text = cells[3].get_text(strip=True)
                    
                    try:
                        sale_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                        sale_price = float(price_text.replace("$", "").replace(",", ""))
                        result["recent_sales"].append({
                            "date": sale_date,
                            "price": sale_price
                        })
                    except (ValueError, AttributeError):
                        continue
        
    except Exception as e:
        print(f"Error scraping {url}: {e}")
    
    return result


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def update_card_market_data(cursor, card_id: int, card_name: str, price: float, 
                            rarity_score: float, market_url: str) -> bool:
    """
    Scrape and update market data for a single card.
    """
    data = scrape_card_market_data(market_url)
    
    # Calculate scores
    supply_score = calculate_supply_score(data["active_listings"], data["sales_per_week"])
    demand_score = calculate_demand_score(data["sales_per_week"], price)
    golden_score = calculate_golden_ratio_score(
        price=price,
        rarity_score=rarity_score or 50,
        supply_score=supply_score,
        demand_score=demand_score,
        character_name=card_name,
        price_change=data["price_change"]
    )
    
    # Update card
    cursor.execute("""
        UPDATE cards SET
            sales_volume_text = ?,
            sales_per_week = ?,
            active_listings = ?,
            price_change = ?,
            release_date = ?,
            supply_score = ?,
            demand_score = ?,
            golden_ratio_score = ?,
            last_market_sync = ?
        WHERE id = ?
    """, (
        data["sales_volume_text"],
        data["sales_per_week"],
        data["active_listings"],
        data["price_change"],
        data["release_date"].isoformat() if data["release_date"] else None,
        supply_score,
        demand_score,
        golden_score,
        datetime.now().isoformat(),
        card_id
    ))
    
    # Insert price history from recent sales
    for sale in data["recent_sales"]:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO price_history (card_id, price, recorded_at, source)
                VALUES (?, ?, ?, 'pricecharting_backfill')
            """, (card_id, sale["price"], sale["date"].isoformat()))
        except Exception:
            pass
    
    return True


def main():
    """
    Main scraper execution.
    """
    print("=" * 70)
    print("🌊 PriceCharting Market Data Scraper")
    print("=" * 70)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get cards with market URLs that haven't been synced recently
    cursor.execute("""
        SELECT id, card_name, price, rarity_score, market_url
        FROM cards
        WHERE market_url IS NOT NULL
          AND market_url != ''
          AND price > 0.50
          AND (last_market_sync IS NULL 
               OR last_market_sync < datetime('now', '-7 days'))
        ORDER BY price DESC
    """)
    
    cards = cursor.fetchall()
    total = len(cards)
    
    print(f"\n📊 Found {total} cards to process")
    print(f"⏱️  Estimated time: {total * RATE_LIMIT_SECONDS / 60:.1f} minutes\n")
    
    success = 0
    errors = 0
    
    for i, (card_id, card_name, price, rarity_score, market_url) in enumerate(cards, 1):
        try:
            print(f"[{i}/{total}] {card_name[:40]:<40} ${price:>8.2f} ... ", end="", flush=True)
            
            if update_card_market_data(cursor, card_id, card_name, price, rarity_score, market_url):
                print("✅")
                success += 1
            else:
                print("⚠️")
                errors += 1
            
            # Commit periodically
            if i % BATCH_SIZE == 0:
                conn.commit()
                print(f"   💾 Committed batch ({success} success, {errors} errors)")
            
            time.sleep(RATE_LIMIT_SECONDS)
            
        except KeyboardInterrupt:
            print("\n\n⚠️ Interrupted! Saving progress...")
            conn.commit()
            break
        except Exception as e:
            print(f"❌ {e}")
            errors += 1
    
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 70)
    print(f"✅ Complete! {success} cards updated, {errors} errors")
    print("=" * 70)


if __name__ == "__main__":
    main()
