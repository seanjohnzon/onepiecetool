from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from tempfile import NamedTemporaryFile
import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..models import Card
from ..schemas import (
    CardCreate,
    CardListResponse,
    CardRead,
    CardUpdate,
)
from ..services import cards as card_service

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
    limit: int = Query(50, gt=0, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> CardListResponse:
    """
    List cards with optional filters and pagination.

    Args:
        set_codes (Optional[List[str]]): Set codes to filter by.
        priority_min (Optional[int]): Minimum priority rank.
        priority_max (Optional[int]): Maximum priority rank.
        search (Optional[str]): Text search for card name.
        variant (Optional[str]): Variant filter.
        scarcity (Optional[str]): Scarcity filter.
        strategy (Optional[str]): Strategy filter.
        limit (int): Page size.
        offset (int): Offset for pagination.
        db (Session): Database session dependency.

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

