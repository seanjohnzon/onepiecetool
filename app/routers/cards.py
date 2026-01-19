from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from tempfile import NamedTemporaryFile
import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

import json

from ..config import Settings, get_settings
from ..database import get_db
from ..models import Card, SavedLot
from ..schemas import (
    CardCreate,
    CardListResponse,
    CardRead,
    CardUpdate,
)
from ..services import cards as card_service
from ..services import trends as trend_service

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("/sets", response_model=dict)
def list_sets(db: Session = Depends(get_db)) -> dict:
    """
    List distinct set codes available in the database.

    Args:
        db (Session): Database session dependency.

    Returns:
        dict: A dictionary containing the list of set codes.
    """

    rows = db.query(Card.set_code).distinct().order_by(Card.set_code).all()
    sets = [row[0] for row in rows]
    return {"sets": sets}


@router.get("/export")
def export_cards(
    set_codes: Optional[List[str]] = Query(None, description="Filter by set codes, or empty for all"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Export cards to Excel file, sorted by priority rank.
    Includes a 'Count Bought' column for user tracking.

    Args:
        set_codes (Optional[List[str]]): Filter by sets, or None for master list.
        db (Session): Database session dependency.

    Returns:
        Response: Excel file download.
    """
    excel_bytes = card_service.export_cards_to_excel(db, set_codes)
    
    filename = "one_piece_tcg_master_list.xlsx"
    if set_codes and len(set_codes) == 1:
        filename = f"one_piece_tcg_{set_codes[0].lower().replace('-', '')}.xlsx"
    
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("", response_model=CardListResponse)
def list_cards(
    set_codes: Optional[List[str]] = Query(None, description="Filter by set code, e.g., OP-05"),
    priority_min: Optional[int] = Query(None, ge=0),
    priority_max: Optional[int] = Query(None, ge=0),
    search: Optional[str] = Query(None, description="Search within card/character name"),
    variant: Optional[str] = Query(None),
    scarcity: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    # New filters
    price_min: Optional[float] = Query(None, ge=0, description="Minimum price"),
    price_max: Optional[float] = Query(None, ge=0, description="Maximum price"),
    rarity_min: Optional[float] = Query(None, ge=0, le=100, description="Minimum rarity score"),
    rarity_max: Optional[float] = Query(None, ge=0, le=100, description="Maximum rarity score"),
    value_score_min: Optional[float] = Query(None, ge=0, description="Minimum value score"),
    value_score_max: Optional[float] = Query(None, ge=0, description="Maximum value score"),
    has_image: Optional[bool] = Query(None, description="Filter by image presence"),
    language: Optional[str] = Query(None, description="Filter by language"),
    variant_type: Optional[str] = Query(None, description="Filter variant type: base, alt_art, promo"),
    sort_by: Optional[str] = Query("price", description="Sort by: price, trend, flip_score, rarity_score, value_score, name, card_number, priority"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    limit: int = Query(50, gt=0, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> CardListResponse:
    """
    List cards with optional filters and pagination.

    Returns:
        CardListResponse: Paginated list of cards.
    """

    total, items = card_service.list_cards(
        db=db,
        set_codes=set_codes,
        priority_min=priority_min,
        priority_max=priority_max,
        search=search,
        variant=variant,
        scarcity=scarcity,
        strategy=strategy,
        price_min=price_min,
        price_max=price_max,
        rarity_min=rarity_min,
        rarity_max=rarity_max,
        value_score_min=value_score_min,
        value_score_max=value_score_max,
        has_image=has_image,
        language=language,
        variant_type=variant_type,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return CardListResponse(total=total, items=items)


@router.post("", response_model=CardRead, status_code=status.HTTP_201_CREATED)
def create_card(card_in: CardCreate, db: Session = Depends(get_db)) -> CardRead:
    """
    Create a card entry.

    Args:
        card_in (CardCreate): Card payload.
        db (Session): Database session dependency.

    Returns:
        CardRead: Created card.
    """

    payload = card_in.model_dump()
    
    # If we have a link, try to auto-populate missing fields
    if payload.get("market_url"):
        try:
            meta = card_service.fetch_market_metadata(payload["market_url"])
            for field in ["set_code", "card_name", "card_number", "variant", "price", "image_url", "language"]:
                if not payload.get(field) and meta.get(field):
                    payload[field] = meta[field]
        except Exception:
            pass

    # Check what's still missing after enrichment
    missing = []
    if not payload.get("set_code"):
        missing.append("set_code")
    if not payload.get("card_name"):
        missing.append("card_name") 
    if not payload.get("card_number"):
        missing.append("card_number")
    
    if missing:
        if payload.get("market_url") and "set_code" in missing and len(missing) == 1:
            # Only set_code is missing - common case for promo/special cards
            raise HTTPException(
                status_code=400, 
                detail="Could not determine the set from the link. Please provide set_code (e.g., OP-13, PRB-01)."
            )
        elif payload.get("market_url"):
            raise HTTPException(
                status_code=400, 
                detail=f"Could not extract {', '.join(missing)} from the link. Please provide manually."
            )
        else:
            raise HTTPException(
                status_code=400, 
                detail="Provide a link OR fill in set_code, card_name, and card_number."
            )

    try:
        card = card_service.create_card(db, CardCreate(**payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CardRead.model_validate(card)


# =============================================================================
# TRENDS & CONFIG ENDPOINTS (must be before /{card_id} routes)
# =============================================================================


@router.post("/prices/capture", response_model=dict)
def capture_prices(db: Session = Depends(get_db)) -> dict:
    """
    Capture today's prices for all cards as a daily snapshot.
    
    Should be called once daily to build price history for trend analysis.
    Safe to call multiple times - won't duplicate entries.
    
    Returns:
        dict: Counts of captured/skipped entries.
    """
    return trend_service.capture_daily_prices(db)


@router.get("/prices/history/{card_id}", response_model=dict)
def get_price_history(
    card_id: int,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
) -> dict:
    """
    Get price history for a specific card.
    
    Args:
        card_id: Card identifier.
        days: Number of days to look back (default 30).
        
    Returns:
        dict: Price history with dates.
    """
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found.")
    
    history = trend_service.get_price_history(db, card_id, days=days)
    return {
        "card_id": card_id,
        "card_name": card.card_name,
        "current_price": card.price,
        "days": days,
        "history": history
    }


@router.post("/trends/update-all", response_model=dict)
def update_all_trends(db: Session = Depends(get_db)) -> dict:
    """
    Update SMA/EMA trends for all eligible cards.
    
    Requires at least min_history_days of price history.
    
    Returns:
        dict: Update statistics.
    """
    return trend_service.update_all_trends(db)


@router.post("/flip-scores/update-all", response_model=dict)
def update_all_flip_scores(db: Session = Depends(get_db)) -> dict:
    """
    Recalculate flip scores for all eligible cards.
    
    Uses current config for thresholds and bonuses.
    
    Returns:
        dict: Update statistics.
    """
    return trend_service.update_all_flip_scores(db)


@router.get("/config", response_model=dict)
def get_config(db: Session = Depends(get_db)) -> dict:
    """
    Get all calculation configuration values.
    
    Returns:
        dict: Configuration key-value pairs.
    """
    return trend_service.get_all_config(db)


@router.patch("/config/{key}", response_model=dict)
def update_config(
    key: str,
    value: float,
    reason: Optional[str] = None,
    db: Session = Depends(get_db)
) -> dict:
    """
    Update a calculation configuration value.
    
    Changes are logged in config_log for audit trail.
    Values are clamped to min/max bounds if set.
    
    Args:
        key: Configuration key.
        value: New value.
        reason: Optional reason for change.
        
    Returns:
        dict: Updated configuration.
    """
    success = trend_service.update_config(db, key, value, reason)
    if not success:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found.")
    
    return {"key": key, "value": value, "status": "updated"}


@router.get("/top-flips", response_model=dict)
def get_top_flips(
    limit: int = Query(20, ge=1, le=100),
    trend_method: str = Query("sma", description="Trend method: sma or ema (legacy, now uses golden_ratio)"),
    character: Optional[str] = Query(None, description="Filter by character name"),
    variant_type: Optional[str] = Query(None, description="Filter by variant type (AA, SP, Promo, etc)"),
    price_min: Optional[float] = Query(None, ge=0, description="Minimum price filter"),
    price_max: Optional[float] = Query(None, ge=0, description="Maximum price filter"),
    db: Session = Depends(get_db)
) -> dict:
    """
    Get top flip opportunities using the Golden Ratio score.
    
    The Golden Ratio score combines supply, demand, character premium,
    rarity, and price tier analysis to find the best flip opportunities.
    
    Args:
        limit: Number of results.
        trend_method: Legacy param (kept for compatibility).
        character: Filter by character name (partial match).
        variant_type: Filter by variant type.
        price_min: Minimum price.
        price_max: Maximum price.
        
    Returns:
        dict: Top flip opportunities ranked by golden_ratio_score.
    """
    from sqlalchemy import text
    
    # Build WHERE clause with optional filters
    # Prioritize golden_ratio_score, fallback to flip_score for older data
    where_clauses = ["(golden_ratio_score IS NOT NULL OR flip_score IS NOT NULL)", "price > 1"]
    params = {"limit": limit}
    
    if character:
        where_clauses.append("LOWER(card_name) LIKE LOWER(:character)")
        params["character"] = f"%{character}%"
    
    if variant_type:
        if variant_type.lower() == "base":
            where_clauses.append("(variant IS NULL OR variant = '' OR variant = 'Base')")
        else:
            where_clauses.append("LOWER(variant) LIKE LOWER(:variant_type)")
            params["variant_type"] = f"%{variant_type}%"
    
    if price_min is not None:
        where_clauses.append("price >= :price_min")
        params["price_min"] = price_min
    
    if price_max is not None:
        where_clauses.append("price <= :price_max")
        params["price_max"] = price_max
    
    where_sql = " AND ".join(where_clauses)
    
    # Query top cards - use golden_ratio_score, fallback to flip_score
    results = db.execute(
        text(f"""
            SELECT id, card_name, card_number, variant, price,
                golden_ratio_score, supply_score, demand_score,
                sales_per_week, active_listings, rarity_score,
                flip_score, image_url, market_url
            FROM cards
            WHERE {where_sql}
            ORDER BY COALESCE(golden_ratio_score, flip_score, 0) DESC
            LIMIT :limit
        """),
        params
    ).fetchall()
    
    cards = []
    for r in results:
        cards.append({
            "id": r[0],
            "card_name": r[1],
            "card_number": r[2],
            "variant": r[3],
            "price": r[4],
            "golden_ratio_score": r[5],
            "supply_score": r[6],
            "demand_score": r[7],
            "sales_per_week": r[8],
            "active_listings": r[9],
            "rarity_score": r[10],
            "flip_score": r[11],  # Legacy fallback
            "image_url": r[12],
            "market_url": r[13],
        })
    
    return {
        "method": "golden_ratio",
        "filters": {"character": character, "variant_type": variant_type},
        "count": len(cards),
        "cards": cards
    }


@router.get("/filter-options", response_model=dict)
def get_filter_options(db: Session = Depends(get_db)) -> dict:
    """
    Get available filter options for characters and variant types.
    
    Returns distinct characters (with flip candidates) and variant types.
    """
    from sqlalchemy import text
    
    # Get distinct characters that have flip potential (flip_score > 0)
    # Only include characters with 3+ cards to avoid clutter
    characters = db.execute(
        text("""
            SELECT card_name, COUNT(*) as cnt
            FROM cards
            WHERE flip_score IS NOT NULL AND flip_score > 0
            GROUP BY card_name
            HAVING COUNT(*) >= 3
            ORDER BY cnt DESC
            LIMIT 50
        """)
    ).fetchall()
    
    # Get distinct variant types
    variants = db.execute(
        text("""
            SELECT DISTINCT variant
            FROM cards
            WHERE flip_score IS NOT NULL AND flip_score > 0
              AND variant IS NOT NULL AND variant != ''
            ORDER BY variant
        """)
    ).fetchall()
    
    # Categorize variants into common types
    variant_categories = [
        {"value": "", "label": "All Variants"},
        {"value": "base", "label": "Base / Standard"},
        {"value": "Alternate Art", "label": "Alternate Art (AA)"},
        {"value": "Manga", "label": "Manga"},
        {"value": "Parallel", "label": "Parallel / Foil"},
        {"value": "Promo", "label": "Promo"},
        {"value": "SP", "label": "SP (Special)"},
        {"value": "Leader", "label": "Leader"},
        {"value": "Championship", "label": "Championship"},
        {"value": "Treasure", "label": "Treasure"},
        {"value": "Super", "label": "Super Rare"},
        {"value": "Gold", "label": "Gold"},
    ]
    
    return {
        "characters": [{"value": r[0], "label": f"{r[0]} ({r[1]} cards)"} for r in characters],
        "variant_types": variant_categories,
        "raw_variants": [r[0] for r in variants]  # All raw variants for reference
    }


# =============================================================================
# SAVED LOTS ENDPOINTS (must be before /{card_id} to match first)
# =============================================================================


@router.get("/saved-lots", response_model=list)
def list_saved_lots(db: Session = Depends(get_db)) -> list:
    """List all saved lots."""
    lots = db.query(SavedLot).order_by(SavedLot.updated_at.desc()).all()
    return [
        {
            "id": lot.id,
            "name": lot.name,
            "description": lot.description,
            "total_value": lot.total_value,
            "card_count": lot.card_count,
            "card_ids": json.loads(lot.card_ids) if lot.card_ids else [],
            "created_at": lot.created_at.isoformat() if lot.created_at else None,
            "updated_at": lot.updated_at.isoformat() if lot.updated_at else None,
        }
        for lot in lots
    ]


@router.post("/saved-lots", response_model=dict)
def create_saved_lot(
    name: str = Query(..., description="Name for the lot"),
    card_ids: List[int] = Query(..., description="List of card IDs"),
    description: Optional[str] = Query(None, description="Optional description"),
    db: Session = Depends(get_db),
) -> dict:
    """Create a new saved lot."""
    # Calculate total value
    cards = db.query(Card).filter(Card.id.in_(card_ids)).all()
    total_value = sum(c.price or 0 for c in cards)
    
    lot = SavedLot(
        name=name,
        description=description,
        total_value=total_value,
        card_count=len(card_ids),
        card_ids=json.dumps(card_ids),
    )
    db.add(lot)
    db.commit()
    db.refresh(lot)
    
    return {
        "id": lot.id,
        "name": lot.name,
        "total_value": lot.total_value,
        "card_count": lot.card_count,
        "message": "Lot saved successfully",
    }


@router.delete("/saved-lots/{lot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_lot(lot_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a saved lot."""
    lot = db.query(SavedLot).filter(SavedLot.id == lot_id).first()
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    db.delete(lot)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# CARD CRUD ENDPOINTS
# =============================================================================


@router.get("/{card_id}", response_model=CardRead)
def get_card(card_id: int, db: Session = Depends(get_db)) -> CardRead:
    """
    Retrieve a single card by id.

    Args:
        card_id (int): Card identifier.
        db (Session): Database session dependency.

    Returns:
        CardRead: Card data.
    """

    card = card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found.")
    return CardRead.model_validate(card)


@router.patch("/{card_id}", response_model=CardRead)
def update_card(card_id: int, card_in: CardUpdate, db: Session = Depends(get_db)) -> CardRead:
    """
    Update a card by id.

    Args:
        card_id (int): Card identifier.
        card_in (CardUpdate): Fields to update.
        db (Session): Database session dependency.

    Returns:
        CardRead: Updated card.
    """

    try:
        card = card_service.update_card(db, card_id, card_in)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not card:
        raise HTTPException(status_code=404, detail="Card not found.")
    return CardRead.model_validate(card)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_card(card_id: int, db: Session = Depends(get_db)) -> Response:
    """
    Delete a card by id.

    Args:
        card_id (int): Card identifier.
        db (Session): Database session dependency.
    """

    deleted = card_service.delete_card(db, card_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Card not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{card_id}/image", response_model=CardRead)
def upload_card_image(
    card_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CardRead:
    """
    Upload and attach an image to a card.

    Args:
        card_id (int): Card identifier.
        file (UploadFile): Uploaded image.
        db (Session): Database session dependency.
        settings (Settings): Application settings dependency.

    Returns:
        CardRead: Updated card.
    """

    try:
        card = card_service.attach_image(db, card_id, file, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not card:
        raise HTTPException(status_code=404, detail="Card not found.")
    return CardRead.model_validate(card)


@router.post("/import/excel", response_model=dict)
def import_excel(
    file: UploadFile = File(...),
    sheet_name: str = Form("MASTER LIST"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Import cards from an uploaded Excel file.

    Args:
        file (UploadFile): Excel workbook to import.
        sheet_name (str): Sheet name to read.
        db (Session): Database session dependency.

    Returns:
        dict: Counts of inserted and updated rows.
    """

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xlsm", ".xls"}:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    with NamedTemporaryFile(delete=True, suffix=suffix) as temp_file:
        content = file.file.read()
        temp_file.write(content)
        temp_file.flush()
        stats = card_service.import_cards_from_excel(db, Path(temp_file.name), sheet_name=sheet_name)
    return stats


@router.post("/{card_id}/market-sync", response_model=CardRead)
def market_sync(
    card_id: int,
    market_url: Optional[str] = None,
    apply_price: bool = True,
    apply_image: bool = True,
    db: Session = Depends(get_db),
) -> CardRead:
    """
    Sync a card's image/price from a market link (e.g., PriceCharting).

    Args:
        card_id (int): Card identifier.
        market_url (Optional[str]): Reference URL to scrape (uses stored URL if omitted).
        apply_price (bool): Overwrite price if found.
        apply_image (bool): Overwrite image_url if found.
        db (Session): Database session dependency.

    Returns:
        CardRead: Updated card.
    """

    card = card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found.")
    target_url = market_url or card.market_url
    if not target_url:
        raise HTTPException(status_code=400, detail="market_url is required.")

    try:
        card = card_service.sync_market_data(
            db=db, card_id=card_id, market_url=target_url, apply_price=apply_price, apply_image=apply_image
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch link: {exc}") from exc
    return CardRead.model_validate(card)


@router.post("/backfill-scores", response_model=dict)
def backfill_scores(db: Session = Depends(get_db)) -> dict:
    """
    Fill missing rarity_score/value_score for existing cards.

    Returns:
        dict: Updated counts.
    """

    updated = card_service.backfill_scores(db)
    db.commit()
    return {"updated": updated}


@router.post("/sync-all/start", response_model=dict)
def start_sync_all(settings: Settings = Depends(get_settings)) -> dict:
    """
    Start background sync of all cards without images.
    
    Syncs cards from PriceCharting in batches with rate limiting.
    Highest value cards are synced first.
    
    Returns:
        dict: Status of the sync job.
    """
    return card_service.start_background_sync(settings.database_url)


@router.post("/sync-all/stop", response_model=dict)
def stop_sync_all() -> dict:
    """
    Stop the background sync.
    
    Returns:
        dict: Confirmation message.
    """
    return card_service.stop_background_sync()


@router.get("/sync-all/status", response_model=dict)
def sync_all_status() -> dict:
    """
    Get status of background sync.
    
    Returns:
        dict: Current sync progress.
    """
    return card_service.get_sync_status()


# =============================================================================
# AI CHAT ENDPOINTS
# =============================================================================

from ..services import ai_chat as ai_service
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Request model for AI chat."""
    message: str
    conversation_history: Optional[list] = None


class ChatResponse(BaseModel):
    """Response model for AI chat."""
    response: Optional[str] = None
    error: Optional[str] = None
    suggested_cards: List[dict] = []


@router.post("/ai/chat", response_model=ChatResponse)
def ai_chat(
    request: ChatRequest,
    db: Session = Depends(get_db)
) -> ChatResponse:
    """
    Chat with Claude AI about card data and analysis.
    
    Send a message and receive AI-powered insights about:
    - Specific cards or characters
    - Flip opportunities and undervalued cards
    - Price trends and predictions
    - Market analysis and strategies
    
    Args:
        request: Chat request with message and optional history.
        db: Database session.
        
    Returns:
        ChatResponse: AI response or error message.
    """
    result = ai_service.chat_with_claude(
        db=db,
        user_message=request.message,
        conversation_history=request.conversation_history
    )
    return ChatResponse(**result)


@router.get("/ai/quick-analysis/{analysis_type}", response_model=dict)
def ai_quick_analysis(
    analysis_type: str,
    db: Session = Depends(get_db)
) -> dict:
    """
    Get pre-built quick analysis.
    
    Available types:
    - top_flips: Best flip opportunities
    - trending_up: Cards with rising prices
    - trending_down: Cards with falling prices
    - chase_cards: Rare/sought-after variants
    - undervalued: Potentially underpriced cards
    
    Args:
        analysis_type: Type of analysis to run.
        db: Database session.
        
    Returns:
        dict: Analysis results.
    """
    return ai_service.get_quick_analysis(db, analysis_type)

