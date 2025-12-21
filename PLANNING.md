# Project Overview
- Build a One Piece TCG investment tracker as a FastAPI app with a SQLite database.
- Import the provided Excel workbook (all sheets, especially `MASTER LIST`) into structured tables.
- Allow card CRUD, image upload/storage, and filtering by set, priority, character/card, variant, scarcity, and strategy.
- Keep files under 500 lines, follow PEP8 with type hints, Google-style docstrings, and format with `black`.

# Stack & Structure
- **Backend:** FastAPI + SQLModel (SQLite for local dev). Pydantic for validation.
- **API server layout:**
  - `app/main.py`: FastAPI app factory + router registration.
  - `app/config.py`: settings (DB path, storage paths, allowed extensions).
  - `app/database.py`: engine/session helpers.
  - `app/models.py`: SQLModel tables (Card, maybe PriceHistory later).
  - `app/schemas.py`: request/response schemas.
  - `app/services/cards.py`: business logic for cards, filtering, and image handling.
  - `app/routers/cards.py`: API routes for CRUD, filters, import.
  - `app/utils/excel_importer.py`: load Excel (`MASTER LIST` default) -> Card rows.
  - `app/static` + `app/templates`: minimal UI for browsing/filtering and uploads.
- **Tests:** `tests/` mirrors app; pytest with httpx AsyncClient against a temp SQLite DB.

# Data Model (initial)
- `Card`: id, set_code, card_name, card_number, variant, scarcity, price, buy_under, priority_manual, priority_logic, strategy, hold_period, liquidity, notes, price_source, last_checked (date), price_1y, roi_1y, price_3y, roi_3y, momentum_score, rarity_score, value_score, auto_priority_value, tcgplayer_search, auto_priority_rank, image_path (local), image_url (optional).
- Derive `set_code` from Excel `Set` column; keep `card_number` as provided (e.g., `OP05-098`).

# Import Pipeline
- Use pandas/openpyxl to read Excel.
- Normalize column names to snake_case and map to Card fields.
- Allow sheet selection (default `MASTER LIST`) and skip empty rows.
- Upsert by unique `(set_code, card_number, variant)` to avoid duplicates.

# API Endpoints (planned)
- `GET /health`
- `GET /cards`: filters (set, priority range, card/character substring, variant, scarcity, strategy, pagination).
- `POST /cards`: create card (optionally with image_url).
- `GET /cards/{card_id}`
- `PATCH /cards/{card_id}`
- `DELETE /cards/{card_id}`
- `POST /cards/{card_id}/image`: upload/store image file.
- `POST /import/excel`: upload Excel and import to DB (sheet param).

# Frontend (minimal)
- Jinja2 templates with HTMX for search/filter and inline create/delete.
- Image upload form per card detail.
- Serve static files from `app/static/`.

# Testing
- Pytest + httpx AsyncClient; use temp SQLite file per test.
- Tests: expected success, edge cases (missing required fields), failure (invalid filters/deletes).

# Open Questions
- Image storage target (local only vs external); default to local `storage/cards`.
- Auth/roles (not requested) – assume open for now.
- Any pagination limits or rate limits? Default limit/offset.

