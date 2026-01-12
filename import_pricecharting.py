"""
Import One Piece cards from PriceCharting CSV into the tracker database.

Run from the One Piece project root:
    python import_pricecharting.py /path/to/one_piece_pricecharting.csv
"""

import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.models import Card, Base
from app.config import get_settings


def extract_card_info(product_name: str) -> dict:
    """
    Extract card number and variant from product name.
    
    Examples:
        "Ain OP07-002" -> {"name": "Ain", "number": "OP07-002", "variant": None}
        "Basil Hawkins [Alternate Art] OP07-029" -> {"name": "Basil Hawkins", "number": "OP07-029", "variant": "Alternate Art"}
        "DON!! Card [Nami]" -> {"name": "DON!! Card", "number": None, "variant": "Nami"}
    """
    # Extract variant in brackets
    variant_match = re.search(r'\[([^\]]+)\]', product_name)
    variant = variant_match.group(1) if variant_match else None
    
    # Remove variant from name for cleaner parsing
    clean_name = re.sub(r'\s*\[[^\]]+\]\s*', ' ', product_name).strip()
    
    # Extract card number (OP07-002, ST01-001, EB01-001, P-001, etc.)
    number_match = re.search(r'(OP\d{2}-\d{3}|ST\d{2}-\d{3}|EB\d{2}-\d{3}|P-\d{3}|PRB-\d{2})', clean_name, re.IGNORECASE)
    card_number = number_match.group(1).upper() if number_match else None
    
    # Remove card number from name
    if card_number:
        card_name = re.sub(rf'\s*{re.escape(card_number)}\s*', '', clean_name, flags=re.IGNORECASE).strip()
    else:
        card_name = clean_name
    
    return {
        "name": card_name,
        "number": card_number,
        "variant": variant
    }


def console_to_set_code(console_name: str) -> str:
    """
    Convert PriceCharting console name to set code.
    
    Examples:
        "One Piece 500 Years in the Future" -> "OP-07"
        "One Piece Japanese Romance Dawn" -> "OP-01"
        "One Piece Starter Deck Straw Hat Crew" -> "ST-01"
    """
    name_lower = console_name.lower()
    
    # Remove "one piece " and "japanese " prefixes
    name_clean = name_lower.replace("one piece ", "").replace("japanese ", "")
    
    # Map set names to codes
    set_mappings = {
        "romance dawn": "OP-01",
        "paramount war": "OP-02",
        "pillars of strength": "OP-03",
        "kingdoms of intrigue": "OP-04",
        "awakening of the new era": "OP-05",
        "wings of the captain": "OP-06",
        "500 years in the future": "OP-07",
        "two legends": "OP-08",
        "emperors in the new world": "OP-09",
        "royal blood": "OP-10",
        "uta": "OP-11",
        "legacy of the master": "OP-12",
        "carrying on his will": "OP-13",
        "fist of divine speed": "OP-14",
        "azure sea's seven": "OP-15",
        "extra booster memorial collection": "EB-01",
        "memorial collection": "EB-01",
        "extra booster anime 25th collection": "EB-02",
        "anime 25th": "EB-02",
        "extra booster heroines edition": "EB-03",
        "heroines edition": "EB-03",
        "premium booster": "PRB-01",
        "premium booster 2": "PRB-02",
        "starter deck straw hat crew": "ST-01",
        "starter deck worst generation": "ST-02",
        "starter deck seven warlords": "ST-03",
        "starter deck animal kingdom pirates": "ST-04",
        "film edition": "ST-05",
        "promo": "P",
        "promos": "P",
        "don cards": "DON",
    }
    
    for pattern, code in set_mappings.items():
        if pattern in name_clean:
            return code
    
    # Default: use first 6 chars
    return name_clean[:6].upper().replace(" ", "-")


def build_pricecharting_url(console_name: str, product_name: str) -> str:
    """
    Build PriceCharting URL from console and product names.
    
    URL format: https://www.pricecharting.com/game/{set-slug}/{product-slug}
    """
    def slugify(text: str) -> str:
        # Convert to lowercase, replace spaces with hyphens, remove special chars
        slug = text.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = re.sub(r'-+', '-', slug)
        return slug.strip('-')
    
    set_slug = slugify(console_name)
    product_slug = slugify(product_name)
    
    return f"https://www.pricecharting.com/game/{set_slug}/{product_slug}"


def parse_price(price_str) -> float:
    """Parse price string like '$1.00' to float."""
    if pd.isna(price_str) or price_str == '' or price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str)
    # Remove $ and commas
    clean = str(price_str).replace('$', '').replace(',', '').strip()
    try:
        return float(clean)
    except ValueError:
        return None


def import_cards(csv_path: str, db_url: str = None, english_only: bool = True):
    """
    Import cards from PriceCharting CSV.
    
    Args:
        csv_path: Path to CSV file
        db_url: Database URL (defaults to settings)
        english_only: Skip Japanese sets if True
    """
    if db_url is None:
        settings = get_settings()
        db_url = settings.database_url
    
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} cards from CSV")
    
    # Filter to English only if requested
    if english_only:
        df = df[~df['console-name'].str.contains('Japanese', case=False, na=False)]
        print(f"Filtered to {len(df)} English cards")
    
    imported = 0
    updated = 0
    skipped = 0
    
    with Session(engine) as db:
        for idx, row in df.iterrows():
            try:
                console_name = row['console-name']
                product_name = row['product-name']
                pricecharting_id = str(row['id'])
                
                # Extract card info
                info = extract_card_info(product_name)
                card_name = info['name']
                card_number = info['number']
                variant = info['variant'] or "Base"
                
                # Get set code
                set_code = console_to_set_code(console_name)
                
                # Build URL
                market_url = build_pricecharting_url(console_name, product_name)
                
                # Parse price (use loose price = ungraded price)
                price = parse_price(row.get('loose-price'))
                
                # Determine language
                language = "Japanese" if "japanese" in console_name.lower() else "English"
                
                # Generate unique card number if missing
                if not card_number:
                    # Use slugified product name as identifier
                    card_number = re.sub(r'[^a-zA-Z0-9]', '_', product_name)[:20].upper()
                
                # Check for existing card
                existing = db.query(Card).filter(
                    Card.set_code == set_code,
                    Card.card_number == card_number,
                    Card.variant == variant
                ).first()
                
                if existing:
                    # Update price and URL
                    if price is not None:
                        existing.price = price
                    existing.market_url = market_url
                    existing.price_source = "PriceCharting CSV"
                    updated += 1
                else:
                    # Create new card
                    card = Card(
                        set_code=set_code,
                        card_name=card_name,
                        card_number=card_number,
                        variant=variant,
                        price=price,
                        market_url=market_url,
                        price_source="PriceCharting CSV",
                        language=language,
                    )
                    db.add(card)
                    imported += 1
                
                if (imported + updated) % 500 == 0:
                    print(f"Progress: {imported} imported, {updated} updated, {skipped} skipped")
                    db.commit()
                
            except Exception as e:
                print(f"Error on row {idx}: {e}")
                skipped += 1
        
        db.commit()
    
    print(f"\n=== IMPORT COMPLETE ===")
    print(f"Imported: {imported}")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Total: {imported + updated}")
    
    return {"imported": imported, "updated": updated, "skipped": skipped}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_pricecharting.py <csv_path> [--japanese]")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    english_only = "--japanese" not in sys.argv
    
    import_cards(csv_path, english_only=english_only)
