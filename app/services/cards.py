from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional
from uuid import uuid4
import re

import pandas as pd
from fastapi import UploadFile
from bs4 import BeautifulSoup
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import Card
from ..schemas import CardCreate, CardRead, CardUpdate


def normalize_variant(variant: Optional[str]) -> str:
    """
    Normalize the variant label for consistent storage.

    Args:
        variant (Optional[str]): Variant provided by the user or importer.

    Returns:
        str: Normalized variant string with a fallback of "Base".
    """

    if variant is None or str(variant).strip() == "":
        return "Base"
    return str(variant).strip()


def adjust_variant_for_language(variant: str, language: Optional[str]) -> str:
    """
    Append language to variant for non-English cards to avoid collisions.
    """

    if language and language.lower() != "english" and language.lower() not in variant.lower():
        return f"{variant} ({language})"
    return variant


def compute_value_score(rarity_score: Optional[float], price: Optional[float]) -> Optional[float]:
    """
    Compute value score as rarity/price when both are present and price > 0.
    """

    if rarity_score is None or price is None:
        return None
    if price <= 0:
        return None
    return round(rarity_score / price, 2)


DEFAULT_LANGUAGE = get_settings().default_language


def detect_rarity_score(variant: Optional[str], scarcity: Optional[str]) -> int:
    """
    Detect rarity score based on variant/scarcity text.

    Mapping (priority order - VARIANT takes precedence over SCARCITY):
      - Manga -> 1 (forced bottom)
      - Leader SP -> 95
      - SP (variant only, not scarcity) -> 90
      - Anniversary -> 85
      - Wanted Poster / WP -> 80
      - Alt Art Leader -> 78
      - Alt Art / Alternate Art / Full Art / AA -> 70
      - Alt Art DON!! -> 65
      - Promo / Stamped / Event -> 68
      - Secret Rare / SEC -> 55
      - Default -> 40

    Args:
        variant (Optional[str]): Variant text.
        scarcity (Optional[str]): Scarcity text.

    Returns:
        int: Rarity score.
    """

    variant_lower = (variant or "").lower().replace("alternate art", "alt art")
    scarcity_lower = (scarcity or "").lower()
    combined = f"{variant_lower} {scarcity_lower}"

    # Forced bottom - manga is always lowest
    if "manga" in combined:
        return 1

    # Check variant FIRST to avoid scarcity overriding it
    # Alt Art variants (must check before SP since scarcity often contains "SP")
    is_alt_art = "alt art" in variant_lower or "full art" in variant_lower or variant_lower == "aa"
    is_leader = "leader" in variant_lower

    if is_alt_art:
        if is_leader:
            return 78  # Alt Art Leader
        if "don" in variant_lower:
            return 65  # Alt Art DON!!
        return 70  # Regular Alt Art / Full Art

    # SP - check variant only (not scarcity) to avoid false positives
    # SP in scarcity like "~1 per case (SP)" should NOT override Alt Art
    is_sp_variant = (
        variant_lower == "sp" or
        variant_lower.startswith("sp ") or
        variant_lower.endswith(" sp") or
        " sp " in variant_lower or
        "(sp)" in variant_lower
    )
    
    if is_leader and is_sp_variant:
        return 95  # Leader SP
    
    if is_sp_variant:
        return 90  # SP

    # Anniversary
    if "anniversary" in combined:
        return 85

    # Wanted Poster / WP
    if "wanted" in variant_lower or "poster" in variant_lower or variant_lower == "wp" or "(wp)" in variant_lower:
        return 80

    # Promo / Stamped / Event
    if "promo" in variant_lower or "stamped" in variant_lower or "event" in variant_lower:
        return 68

    # Secret Rare
    if "secret" in variant_lower or variant_lower == "sec" or "(sec)" in variant_lower:
        return 55

    return 40


def recompute_priority_ranks(db: Session) -> int:
    """
    Recompute auto_priority_rank for all cards based on value_score.

    Highest value_score = rank 1, second highest = rank 2, etc.
    Cards with no value_score are ranked last (nulls last).

    Args:
        db (Session): Database session.

    Returns:
        int: Number of cards updated.
    """

    # Get all cards ordered by value_score descending (nulls last)
    cards = (
        db.query(Card)
        .order_by(Card.value_score.desc().nullslast(), Card.id.asc())
        .all()
    )
    updated = 0
    for rank, card in enumerate(cards, start=1):
        if card.auto_priority_rank != rank:
            card.auto_priority_rank = rank
            updated += 1
    return updated


def backfill_scores(db: Session) -> int:
    """
    Fill missing rarity_score/value_score for existing cards, then recompute priority ranks.

    Args:
        db (Session): Database session.

    Returns:
        int: Number of cards updated.
    """

    updated = 0
    for card in db.query(Card).all():
        changed = False
        if card.rarity_score is None or card.rarity_score == 0:
            card.rarity_score = float(detect_rarity_score(card.variant, card.scarcity))
            changed = True
        computed_value = compute_value_score(card.rarity_score, card.price)
        if computed_value is not None and card.value_score != computed_value:
            card.value_score = computed_value
            changed = True
        if changed:
            updated += 1
    # After updating scores, recompute priority ranks
    recompute_priority_ranks(db)
    return updated


def ensure_unique_identity(
    db: Session, set_code: str, card_number: str, variant: str, exclude_id: Optional[int] = None
) -> None:
    """
    Ensure no other card shares the identity trio (set, number, variant).

    Args:
        db (Session): Database session.
        set_code (str): Card set code.
        card_number (str): Card number.
        variant (str): Variant label.
        exclude_id (Optional[int]): Card id to exclude when checking during updates.

    Raises:
        ValueError: If a duplicate card exists.
    """

    query = select(Card.id).where(
        Card.set_code == set_code,
        Card.card_number == card_number,
        Card.variant == variant,
    )
    if exclude_id:
        query = query.where(Card.id != exclude_id)
    exists = db.execute(query).first()
    if exists:
        raise ValueError("Card already exists for this set, card number, and variant.")


def create_card(db: Session, card_in: CardCreate) -> Card:
    """
    Create a new card record.

    Args:
        db (Session): Database session.
        card_in (CardCreate): Card payload.

    Returns:
        Card: Persisted card.

    Raises:
        ValueError: When a duplicate card exists.
    """

    if not card_in.set_code or not card_in.card_name or not card_in.card_number:
        raise ValueError("set_code, card_name, and card_number are required to create a card.")

    language = card_in.language or DEFAULT_LANGUAGE
    variant_value = adjust_variant_for_language(normalize_variant(card_in.variant), language)
    ensure_unique_identity(db, card_in.set_code, card_in.card_number, variant_value)
    data = card_in.model_dump()
    data["variant"] = variant_value
    data["language"] = language
    if data.get("rarity_score") is None:
        data["rarity_score"] = float(detect_rarity_score(data.get("variant"), data.get("scarcity")))
    value_score = compute_value_score(data.get("rarity_score"), data.get("price"))
    data["value_score"] = value_score if value_score is not None else data.get("value_score")
    card = Card(**data)
    db.add(card)
    db.commit()
    db.refresh(card)
    # Recompute priority ranks after adding a new card
    recompute_priority_ranks(db)
    db.commit()
    db.refresh(card)
    return card


def get_card(db: Session, card_id: int) -> Optional[Card]:
    """
    Retrieve a card by id.

    Args:
        db (Session): Database session.
        card_id (int): Card identifier.

    Returns:
        Optional[Card]: Card if found, otherwise None.
    """

    return db.get(Card, card_id)


def update_card(db: Session, card_id: int, card_in: CardUpdate) -> Optional[Card]:
    """
    Update an existing card.

    Args:
        db (Session): Database session.
        card_id (int): Card identifier.
        card_in (CardUpdate): Fields to update.

    Returns:
        Optional[Card]: Updated card or None if not found.

    Raises:
        ValueError: If the update would create a duplicate identity.
    """

    card = db.get(Card, card_id)
    if not card:
        return None

    update_data = card_in.model_dump(exclude_unset=True)
    if "variant" in update_data:
        update_data["variant"] = normalize_variant(update_data["variant"])

    set_code = update_data.get("set_code", card.set_code)
    card_number = update_data.get("card_number", card.card_number)
    variant_value = update_data.get("variant", card.variant)
    ensure_unique_identity(db, set_code, card_number, variant_value, exclude_id=card.id)

    for field, value in update_data.items():
        setattr(card, field, value)
    variant_changed = "variant" in update_data or "scarcity" in update_data
    rarity_explicitly_set = "rarity_score" in update_data and update_data.get("rarity_score") is not None
    if not rarity_explicitly_set and (card.rarity_score is None or variant_changed):
        # Reason: keep rarity populated when missing, and keep in sync with variant/scarcity changes
        card.rarity_score = float(detect_rarity_score(card.variant, card.scarcity))

    if "rarity_score" in update_data or "price" in update_data or variant_changed:
        value_score = compute_value_score(card.rarity_score, card.price)
        card.value_score = value_score if value_score is not None else card.value_score
    db.commit()
    db.refresh(card)
    return card


def delete_card(db: Session, card_id: int) -> bool:
    """
    Delete a card by id.

    Args:
        db (Session): Database session.
        card_id (int): Card identifier.

    Returns:
        bool: True if deleted, False if not found.
    """

    card = db.get(Card, card_id)
    if not card:
        return False
    db.delete(card)
    db.commit()
    return True


def list_cards(
    db: Session,
    set_codes: Optional[list[str]],
    priority_min: Optional[int],
    priority_max: Optional[int],
    search: Optional[str],
    variant: Optional[str],
    scarcity: Optional[str],
    strategy: Optional[str],
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    rarity_min: Optional[float] = None,
    rarity_max: Optional[float] = None,
    value_score_min: Optional[float] = None,
    value_score_max: Optional[float] = None,
    has_image: Optional[bool] = None,
    language: Optional[str] = None,
    variant_type: Optional[str] = None,
    sort_by: Optional[str] = "price",
    sort_order: Optional[str] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Card]]:
    """
    Fetch cards with filtering and pagination.

    Returns:
        tuple[int, list[Card]]: Total count and list of cards.
    """

    query = db.query(Card)
    
    # Set filter
    if set_codes:
        query = query.filter(Card.set_code.in_(set_codes))
    
    # Priority filters
    if priority_min is not None:
        query = query.filter(Card.priority_manual >= priority_min)
    if priority_max is not None:
        query = query.filter(Card.priority_manual <= priority_max)
    
    # Text search
    if search:
        search_term = f"%{search.lower()}%"
        query = query.filter(func.lower(Card.card_name).like(search_term))
    
    # Variant filter (exact match)
    if variant:
        query = query.filter(Card.variant == normalize_variant(variant))
    
    # Scarcity filter
    if scarcity:
        query = query.filter(func.lower(Card.scarcity) == scarcity.lower())
    
    # Strategy filter
    if strategy:
        query = query.filter(func.lower(Card.strategy) == strategy.lower())
    
    # Price range filters
    if price_min is not None:
        query = query.filter(Card.price >= price_min)
    if price_max is not None:
        query = query.filter(Card.price <= price_max)
    
    # Rarity score filters
    if rarity_min is not None:
        query = query.filter(Card.rarity_score >= rarity_min)
    if rarity_max is not None:
        query = query.filter(Card.rarity_score <= rarity_max)
    
    # Value score filters
    if value_score_min is not None:
        query = query.filter(Card.value_score >= value_score_min)
    if value_score_max is not None:
        query = query.filter(Card.value_score <= value_score_max)
    
    # Has image filter
    if has_image is not None:
        if has_image:
            query = query.filter(Card.image_url.isnot(None), Card.image_url != "")
        else:
            query = query.filter((Card.image_url.is_(None)) | (Card.image_url == ""))
    
    # Language filter
    if language:
        query = query.filter(func.lower(Card.language) == language.lower())
    
    # Variant type filter (base, alt_art, promo)
    if variant_type:
        variant_lower = variant_type.lower()
        if variant_lower == "base":
            query = query.filter(
                (Card.variant.is_(None)) | 
                (func.lower(Card.variant) == "base") |
                (Card.variant == "")
            )
        elif variant_lower in ("alt_art", "alternate_art", "alt"):
            query = query.filter(
                func.lower(Card.variant).like("%alt%") |
                func.lower(Card.variant).like("%alternate%")
            )
        elif variant_lower == "promo":
            query = query.filter(func.lower(Card.variant).like("%promo%"))
        elif variant_lower == "leader":
            query = query.filter(func.lower(Card.variant).like("%leader%"))

    total = query.count()
    
    # Sorting
    sort_column_map = {
        "price": Card.price,
        "rarity_score": Card.rarity_score,
        "value_score": Card.value_score,
        "name": Card.card_name,
        "card_number": Card.card_number,
        "priority": Card.auto_priority_rank,
    }
    
    sort_col = sort_column_map.get(sort_by, Card.price)
    
    if sort_order == "asc":
        order_clause = sort_col.asc().nullslast()
    else:
        order_clause = sort_col.desc().nullslast()
    
    items = (
        query.order_by(order_clause)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return total, items


def save_image_file(
    upload: UploadFile, settings: Settings
) -> tuple[Path, str]:
    """
    Persist an uploaded image to disk.

    Args:
        upload (UploadFile): Incoming upload.
        settings (Settings): Application settings.

    Returns:
        tuple[Path, str]: Saved absolute path and public relative URL.

    Raises:
        ValueError: If the file extension is not allowed or exceeds size limits.
    """

    suffix = Path(upload.filename or "").suffix.lower().lstrip(".")
    if suffix not in settings.allowed_image_extensions:
        raise ValueError(f"Unsupported image type: {suffix}")

    content = upload.file.read()
    if len(content) > settings.upload_max_bytes:
        raise ValueError("File too large.")

    file_name = f"{uuid4().hex}.{suffix}"
    dest_path = settings.storage_dir / file_name
    dest_path.write_bytes(content)
    public_path = f"/media/cards/{file_name}"
    return dest_path, public_path


def attach_image(
    db: Session, card_id: int, upload: UploadFile, settings: Settings
) -> Optional[Card]:
    """
    Attach an uploaded image to a card.

    Args:
        db (Session): Database session.
        card_id (int): Card identifier.
        upload (UploadFile): Uploaded image file.
        settings (Settings): Application settings.

    Returns:
        Optional[Card]: Updated card or None if not found.
    """

    card = db.get(Card, card_id)
    if not card:
        return None

    _, public_path = save_image_file(upload, settings)
    card.image_path = public_path
    db.commit()
    db.refresh(card)
    return card


def fetch_market_metadata(url: str, timeout: float = 10.0) -> dict:
    """
    Fetch market page metadata (image, price) from a reference URL.

    Args:
        url (str): Market/listing URL.
        timeout (float): Request timeout in seconds.

    Returns:
        dict: Parsed metadata containing image_url, price, and variant if available.
    """

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    resp = httpx.get(url, timeout=timeout, headers=headers, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    image_url = None
    price_value = None
    variant_value = None

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        image_url = og_image["content"]
    if not image_url:
        first_img = soup.find("img")
        if first_img and first_img.get("src"):
            image_url = first_img["src"]

    # Try common price markers
    price_candidates = []
    for attr in [
        {"itemprop": "price"},
        {"property": "product:price:amount"},
        {"data-price": True},
    ]:
        tag = soup.find(attrs=attr)
        if tag and tag.get("content"):
            price_candidates.append(tag["content"])
        if tag and tag.text:
            price_candidates.append(tag.text)

    for tag in soup.find_all(class_=lambda x: x and "price" in x.lower()):
        if tag.text:
            price_candidates.append(tag.text)
        if tag.get("data-price"):
            price_candidates.append(tag["data-price"])

    # Variant: look at og:title or title content for bracket/parenthesis tokens
    title_text = None
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title_text = og_title["content"]
    elif soup.title and soup.title.text:
        title_text = soup.title.text
    url_text = url or ""

    def extract_variant_from_title(text: str) -> Optional[str]:
        import re

        # Prefer bracketed content like [SP] or [Alt Art]
        match = re.search(r"\[([^\]]+)\]", text)
        if match:
            return match.group(1).strip()
        # Fallback to parenthesis content
        match = re.search(r"\(([^)]+)\)", text)
        if match:
            return match.group(1).strip()
        return None

    if title_text:
        variant_value = extract_variant_from_title(title_text)

    def extract_card_number(text: str) -> Optional[str]:
        import re

        # Match various One Piece card number formats:
        # OP01-001, EB02-028, ST01-001, P-001, PRB-01, etc.
        patterns = [
            r"(OP\s?\d{2}-\d{3})",      # OP01-001
            r"(EB\s?\d{2}-\d{3})",      # EB02-028
            r"(ST\s?\d{2}-\d{3})",      # ST01-001
            r"(PRB-\d{2})",             # PRB-01
            r"(P-\d{3})",               # P-001
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                raw = match.group(1).upper().replace(" ", "")
                return raw
        return None

    def generate_card_id_from_url(url_str: str) -> Optional[str]:
        """Generate a unique card identifier from URL slug when no standard number exists."""
        import re
        from urllib.parse import urlparse
        # Parse URL to get just the path, ignoring query params
        parsed = urlparse(url_str)
        path = parsed.path
        # Extract the last segment (card slug)
        segments = [s for s in path.split("/") if s]
        if segments:
            slug = segments[-1]
            # Convert slug to uppercase with underscores, max 20 chars
            card_id = slug.upper().replace("-", "_")[:20]
            return card_id
        return None

    card_number = None
    for candidate in [title_text or "", url_text]:
        card_number = extract_card_number(candidate)
        if card_number:
            break
    
    # If no standard card number found, generate from URL
    if not card_number:
        card_number = generate_card_id_from_url(url_text)

    def derive_set_code(cn: str) -> Optional[str]:
        if not cn:
            return None
        import re
        # Extract prefix like OP, EB, ST and number
        match = re.match(r"([A-Z]+)(\d{2})", cn)
        if match:
            prefix = match.group(1)
            num = match.group(2)
            return f"{prefix}-{num}"
        return None

    def derive_set_from_url(url_str: str) -> Optional[str]:
        """Try to derive set code from URL path (the game/set segment, not the card name)."""
        from urllib.parse import urlparse
        parsed = urlparse(url_str)
        path_parts = [p for p in parsed.path.lower().split("/") if p]
        
        # Look for set name in the path (usually the second segment after "game")
        # URL format: /game/{set-name}/{card-name}
        set_segment = None
        for i, part in enumerate(path_parts):
            if part == "game" and i + 1 < len(path_parts):
                set_segment = path_parts[i + 1]
                break
        
        if not set_segment:
            return None
            
        # Map known URL patterns to set codes (check in set_segment only)
        # More specific patterns should come first (e.g., premium-booster-2 before premium-booster)
        set_mappings = [
            ("romance-dawn", "OP-01"),
            ("japanese-romance-dawn", "OP-01"),
            ("paramount-war", "OP-02"),
            ("japanese-paramount-war", "OP-02"),
            ("pillars-of-strength", "OP-03"),
            ("kingdoms-of-intrigue", "OP-04"),
            ("awakening-of-the-new-era", "OP-05"),
            ("wings-of-the-captain", "OP-06"),
            ("500-years-in-the-future", "OP-07"),
            ("two-legends", "OP-08"),
            ("emperors-in-the-new-world", "OP-09"),
            ("royal-bloodlines", "OP-10"),
            ("uta", "OP-11"),
            ("memorial-collection", "OP-12"),
            ("legacy-of-the-master", "OP-12"),
            ("carrying-on-his-will", "OP-13"),
            ("japanese-carrying-on-his-will", "OP-13"),
            ("premium-booster-2", "PRB-02"),  # Must come before premium-booster
            ("premium-booster", "PRB-01"),
            ("starter-deck", "ST-01"),
        ]
        for pattern, code in set_mappings:
            if pattern in set_segment:
                return code
        return None

    # Try URL-based detection first for PRB sets (they often have EB card numbers)
    url_set_code = derive_set_from_url(url_text)
    if url_set_code and url_set_code.startswith("PRB"):
        set_code = url_set_code
    else:
        # Fall back to card number-based detection, then URL
        set_code = derive_set_code(card_number) if card_number else None
        if not set_code:
            set_code = url_set_code

    def extract_card_name(text: str, cn: Optional[str]) -> Optional[str]:
        if not text:
            return None
        cleaned = text
        for pattern in [r"\[[^\]]+\]", r"\([^)]+\)"]:
            cleaned = re.sub(pattern, "", cleaned).strip()
        if cn:
            cleaned = cleaned.replace(cn, "").strip()
        # Strip separators
        for sep in ["-", "|", "•", ":"]:
            if sep in cleaned:
                parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
                if parts:
                    cleaned = parts[0]
                    break
        if "Prices" in cleaned:
            cleaned = cleaned.replace("Prices", "").strip()
        return cleaned if cleaned else None

    card_name = extract_card_name(title_text or "", card_number)

    def detect_language(texts: list[str]) -> Optional[str]:
        for txt in texts:
            lower = txt.lower()
            if "japanese" in lower or "jp " in lower or " jp" in lower:
                return "Japanese"
            if "english" in lower or "eng " in lower or " eng" in lower:
                return "English"
        return None

    language = detect_language([title_text or "", url_text])
    if not language:
        # default to English if not explicitly Japanese
        language = "English"

    def extract_first_number(text: str) -> Optional[float]:
        import re

        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
        if match:
            try:
                return round(float(match.group(1)), 2)
            except ValueError:
                return None
        return None

    for candidate in price_candidates:
        if isinstance(candidate, str):
            val = extract_first_number(candidate)
            if val is not None:
                price_value = val
                break

    return {
        "image_url": image_url,
        "price": price_value,
        "market_url": url,
        "variant": variant_value,
        "card_number": card_number,
        "set_code": set_code,
        "card_name": card_name,
        "language": language,
    }


def sync_market_data(
    db: Session,
    card_id: int,
    market_url: str,
    apply_price: bool = True,
    apply_image: bool = True,
) -> Optional[Card]:
    """
    Fetch market metadata and update a card with image URL, price, and correct set/card info.

    Args:
        db (Session): Database session.
        card_id (int): Card identifier.
        market_url (str): Reference URL to scrape.
        apply_price (bool): Whether to overwrite price if found.
        apply_image (bool): Whether to overwrite image_url if found.

    Returns:
        Optional[Card]: Updated card or None if not found.
    """

    card = db.get(Card, card_id)
    if not card:
        return None
    meta = fetch_market_metadata(market_url)
    card.market_url = market_url
    if not meta.get("language"):
        meta["language"] = card.language or DEFAULT_LANGUAGE
    if apply_price and meta.get("price") is not None:
        card.price = meta["price"]
        card.price_source = card.price_source or "Market link"
    if apply_image and meta.get("image_url"):
        card.image_url = meta["image_url"]
    if meta.get("variant"):
        card.variant = adjust_variant_for_language(meta["variant"], meta.get("language") or card.language)
    if meta.get("language"):
        card.language = meta["language"]
    # Update card_number and card_name from link if available
    # But KEEP the user's set_code - they may want to organize cards differently
    # (e.g., EB02 promo cards filed under OP-13)
    if meta.get("card_number"):
        card.card_number = meta["card_number"]
    if meta.get("card_name"):
        card.card_name = meta["card_name"]
    # Always recalculate rarity score based on current variant
    card.rarity_score = float(detect_rarity_score(card.variant, card.scarcity))
    value_score = compute_value_score(card.rarity_score, card.price)
    if value_score is not None:
        card.value_score = value_score
    db.commit()
    # Recompute priority ranks after sync updates value_score
    recompute_priority_ranks(db)
    db.commit()
    db.refresh(card)
    return card


COLUMN_MAP = {
    "Set": "set_code",
    "Card": "card_name",
    "Card No.": "card_number",
    "Variant": "variant",
    "Scarcity": "scarcity",
    "Price $": "price",
    "Buy-Under $": "buy_under",
    "Priority (1=Top)": "priority_manual",
    "Priority Logic": "priority_logic",
    "Strategy": "strategy",
    "Hold Period": "hold_period",
    "Liquidity": "liquidity",
    "Notes": "notes",
    "Price Source": "price_source",
    "Last Checked": "last_checked",
    "Price 1Y Ago $": "price_1y",
    "ROI 1Y %": "roi_1y",
    "Price 3Y Ago $": "price_3y",
    "ROI 3Y %": "roi_3y",
    "Momentum Score (Manual)": "momentum_score",
    "Rarity Score": "rarity_score",
    "Value Score (Rarity/Price)": "value_score",
    "Auto Priority (by Value Score)": "auto_priority_value",
    "TCGPlayer Search (auto)": "tcgplayer_search",
    "Auto Priority": "auto_priority_rank",
}


def parse_row_to_payload(row: dict) -> CardCreate:
    """
    Convert a pandas row dict to a CardCreate payload.

    Args:
        row (dict): Row data with mapped keys.

    Returns:
        CardCreate: Payload ready for creation.
    """

    cleaned = {k: v for k, v in row.items() if v == v}  # drop NaN
    str_fields = {
        "set_code",
        "card_name",
        "card_number",
        "variant",
        "scarcity",
        "priority_logic",
        "strategy",
        "hold_period",
        "liquidity",
        "notes",
        "price_source",
        "tcgplayer_search",
        "image_url",
        "market_url",
    }
    for key in list(cleaned.keys()):
        if key in str_fields and cleaned.get(key) is not None:
            cleaned[key] = str(cleaned[key]).strip()
    last_checked = cleaned.get("last_checked")
    if isinstance(last_checked, (float, int)):
        cleaned["last_checked"] = None
    elif isinstance(last_checked, pd.Timestamp):
        cleaned["last_checked"] = last_checked.date()
    elif isinstance(last_checked, str):
        try:
            cleaned["last_checked"] = pd.to_datetime(last_checked).date()
        except Exception:
            cleaned["last_checked"] = None
    return CardCreate(**cleaned)


def import_cards_from_excel(
    db: Session, file_path: Path, sheet_name: str = "MASTER LIST"
) -> dict:
    """
    Import cards from an Excel file into the database (upsert).

    Args:
        db (Session): Database session.
        file_path (Path): Path to the Excel file.
        sheet_name (str): Sheet name to import.

    Returns:
        dict: Counts of inserted and updated records.
    """

    def import_dataframe(
        df: pd.DataFrame, pending_map: dict[tuple[str, str, str], Card], default_set_code: str | None
    ) -> dict:
        required = {"set_code", "card_name", "card_number"}
        counts = {"inserted": 0, "updated": 0, "skipped": 0}

        for _, row in df.iterrows():
            payload = row.to_dict()
            if ("set_code" not in payload or pd.isna(payload.get("set_code")) or str(payload.get("set_code")).strip() == "") and default_set_code:
                payload["set_code"] = default_set_code
            missing_required = [
                field
                for field in required
                if pd.isna(payload.get(field)) or str(payload.get(field)).strip() == ""
            ]
            if missing_required:
                counts["skipped"] += 1
                continue
            card_payload = parse_row_to_payload(payload)
            variant_value = adjust_variant_for_language(
                normalize_variant(card_payload.variant), card_payload.language
            )
            if not card_payload.language:
                card_payload.language = DEFAULT_LANGUAGE
            if card_payload.rarity_score is None:
                card_payload.rarity_score = float(detect_rarity_score(variant_value, card_payload.scarcity))
            identity = (card_payload.set_code, card_payload.card_number, variant_value)
            existing = pending_map.get(identity)
            if not existing:
                existing = (
                    db.query(Card)
                    .filter(
                        Card.set_code == card_payload.set_code,
                        Card.card_number == card_payload.card_number,
                        Card.variant == variant_value,
                    )
                    .first()
                )
            data = card_payload.model_dump()
            data["variant"] = variant_value
            value_score = compute_value_score(data.get("rarity_score"), data.get("price"))
            if value_score is not None:
                data["value_score"] = value_score
            if existing:
                for field, value in data.items():
                    setattr(existing, field, value)
                existing.value_score = compute_value_score(existing.rarity_score, existing.price) or existing.value_score
                counts["updated"] += 1
            else:
                card = Card(**data)
                db.add(card)
                pending_map[identity] = card
                counts["inserted"] += 1
        return counts

    excel_file = pd.ExcelFile(file_path)
    if sheet_name is None or sheet_name.upper() == "ALL":
        sheet_names = excel_file.sheet_names
    elif sheet_name not in excel_file.sheet_names:
        sheet_names = excel_file.sheet_names[:1]
    else:
        sheet_names = [sheet_name]

    inserted = 0
    updated = 0
    per_sheet: dict[str, dict[str, int]] = {}
    pending: dict[tuple[str, str, str], Card] = {}

    for sheet in sheet_names:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
        except ValueError:
            continue
        if df.empty:
            per_sheet[sheet] = {"inserted": 0, "updated": 0, "skipped": 0}
            continue
        df = df.rename(columns=COLUMN_MAP)
        default_set_code = sheet.split()[0] if sheet else None
        if "set_code" not in df.columns:
            df["set_code"] = default_set_code
        else:
            df["set_code"] = df["set_code"].fillna(default_set_code)
        counts = import_dataframe(df, pending, default_set_code)
        per_sheet[sheet] = counts
        inserted += counts["inserted"]
        updated += counts["updated"]

    db.commit()
    # Recompute priority ranks after import
    recompute_priority_ranks(db)
    db.commit()
    return {
        "inserted": inserted,
        "updated": updated,
        "total": inserted + updated,
        "per_sheet": per_sheet,
    }


def export_cards_to_excel(db: Session, set_codes: Optional[list[str]] = None) -> bytes:
    """
    Export cards to Excel format, sorted by priority rank.
    Includes a 'Count Bought' column for user tracking.

    Args:
        db (Session): Database session.
        set_codes (Optional[list[str]]): Filter by specific sets, or None for all.

    Returns:
        bytes: Excel file content as bytes.
    """
    from io import BytesIO

    query = db.query(Card)
    if set_codes:
        query = query.filter(Card.set_code.in_(set_codes))

    # Order by priority rank (best value first)
    cards = query.order_by(
        Card.auto_priority_rank.asc().nullslast(),
        Card.value_score.desc().nullslast(),
    ).all()

    # Build data for export
    data = []
    for card in cards:
        data.append({
            "Priority": card.auto_priority_rank,
            "Set": card.set_code,
            "Card Name": card.card_name,
            "Card Number": card.card_number,
            "Variant": card.variant,
            "Language": card.language or "English",
            "Avg Price ($)": card.price,
            "Rarity Score": card.rarity_score,
            "Value Score": card.value_score,
            "Count Bought": "",  # Empty column for user to fill in
            "Market URL": card.market_url or "",
        })

    df = pd.DataFrame(data)

    # Write to Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Master List", index=False)
        
        # Auto-adjust column widths
        worksheet = writer.sheets["Master List"]
        for i, col in enumerate(df.columns):
            max_length = max(
                df[col].astype(str).map(len).max() if len(df) > 0 else 0,
                len(col)
            ) + 2
            worksheet.column_dimensions[chr(65 + i)].width = min(max_length, 50)

    return output.getvalue()


# =============================================================================
# BACKGROUND SYNC ALL
# =============================================================================

import threading
import time

# Global sync status
_sync_status = {
    "running": False,
    "total": 0,
    "synced": 0,
    "failed": 0,
    "current_card": None,
    "errors": [],
}


def get_sync_status() -> dict:
    """Get current sync status."""
    return _sync_status.copy()


def sync_all_cards_background(db_url: str, batch_size: int = 5, delay_seconds: float = 5.0):
    """
    Sync all cards that don't have images in background.
    
    Args:
        db_url: Database URL for creating new session.
        batch_size: Cards to sync before sleeping.
        delay_seconds: Seconds to wait between batches.
    """
    global _sync_status
    
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SqlSession
    
    _sync_status = {
        "running": True,
        "total": 0,
        "synced": 0,
        "failed": 0,
        "current_card": None,
        "errors": [],
    }
    
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    
    try:
        with SqlSession(engine) as db:
            # Get cards without images that have market_url
            cards_to_sync = db.query(Card).filter(
                Card.market_url.isnot(None),
                Card.market_url != "",
                (Card.image_url.is_(None)) | (Card.image_url == "")
            ).order_by(Card.price.desc()).all()  # Highest value first
            
            _sync_status["total"] = len(cards_to_sync)
            
            if _sync_status["total"] == 0:
                _sync_status["running"] = False
                return
            
            for i, card in enumerate(cards_to_sync):
                if not _sync_status["running"]:
                    break  # Allow stopping
                
                _sync_status["current_card"] = f"{card.card_name} ({card.card_number})"
                
                try:
                    meta = fetch_market_metadata(card.market_url)
                    
                    if meta.get("image_url"):
                        card.image_url = meta["image_url"]
                    if meta.get("price") is not None:
                        card.price = meta["price"]
                    if meta.get("variant"):
                        card.variant = adjust_variant_for_language(
                            meta["variant"], 
                            meta.get("language") or card.language
                        )
                    
                    # Recalculate scores
                    card.rarity_score = float(detect_rarity_score(card.variant, card.scarcity))
                    value_score = compute_value_score(card.rarity_score, card.price)
                    if value_score is not None:
                        card.value_score = value_score
                    
                    db.commit()
                    _sync_status["synced"] += 1
                    
                except Exception as e:
                    _sync_status["failed"] += 1
                    if len(_sync_status["errors"]) < 10:
                        _sync_status["errors"].append(f"{card.card_number}: {str(e)[:50]}")
                
                # Rate limiting
                if (i + 1) % batch_size == 0:
                    time.sleep(delay_seconds)
            
            # Final recompute of priority ranks
            recompute_priority_ranks(db)
            db.commit()
            
    finally:
        _sync_status["running"] = False
        _sync_status["current_card"] = None


def start_background_sync(db_url: str) -> dict:
    """
    Start background sync in a separate thread.
    
    Args:
        db_url: Database URL.
        
    Returns:
        Status dict.
    """
    global _sync_status
    
    if _sync_status["running"]:
        return {"status": "already_running", **_sync_status}
    
    thread = threading.Thread(
        target=sync_all_cards_background,
        args=(db_url,),
        daemon=True
    )
    thread.start()
    
    return {"status": "started", "message": "Background sync started"}


def stop_background_sync() -> dict:
    """Stop the background sync."""
    global _sync_status
    _sync_status["running"] = False
    return {"status": "stopping", "message": "Sync will stop after current card"}

