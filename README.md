# One Piece TCG Tracker

FastAPI-powered tracker for One Piece TCG chase cards. Import the provided Excel, browse/filter cards, attach images, and manage entries.

## Features
- Import Excel (`MASTER LIST` by default) into SQLite (upsert on set + card number + variant).
- CRUD API for cards plus filtering by set, priority range, name, variant, scarcity, and strategy.
- Image upload per card, served from `/media/cards`.
- Minimal web UI (FastAPI + Jinja + vanilla JS) for filters, creation, import, and image upload.
- Pytest coverage for core flows (create/get, duplicate protection, filters, Excel import).

## Setup
```bash
cd "/Users/sahcihansahin/One Piece"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running
```bash
uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000/ to use the UI.

## Importing the Excel
- UI: use the "Import Excel" form (sheet defaults to `MASTER LIST`).
- API: `POST /cards/import/excel` with multipart file and optional `sheet_name` (use `ALL` to import every sheet).
- CLI (example):
```bash
python3 - <<'PY'
from pathlib import Path
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import SessionLocal
from app.models import Base
from app.services.cards import import_cards_from_excel
from app.database import engine

Base.metadata.create_all(bind=engine)
settings = get_settings()
excel_path = Path("/Users/sahcihansahin/Downloads/One_Piece_TCG_Investment_Playbook_v9_Rarity_Priority_Final.xlsx")
with SessionLocal() as session:
    print(import_cards_from_excel(session, excel_path, sheet_name="MASTER LIST"))
PY
```

## API Cheat Sheet
- `GET /cards` query params: `set_codes`, `priority_min`, `priority_max`, `search`, `variant`, `scarcity`, `strategy`, `limit`, `offset`.
- `POST /cards` → create.
- `GET /cards/{id}` → read.
- `PATCH /cards/{id}` → partial update.
- `DELETE /cards/{id}` → delete.
- `POST /cards/{id}/image` multipart `file`.
- `POST /cards/import/excel` multipart `file`, form `sheet_name`.

## Testing
```bash
pytest
```

## Notes
- Images save to `storage/cards`; served at `/media/cards/{filename}`.
- Unique identity is `set_code + card_number + variant` (variant defaults to `Base`).

