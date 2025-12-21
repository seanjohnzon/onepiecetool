from pathlib import Path
import sys

import pandas as pd
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from app.config import Settings, get_settings
from app.database import get_db
from app.main import app
from app.models import Base


def build_test_app(tmp_path: Path) -> TestClient:
    """
    Configure a TestClient with an isolated SQLite database and storage.

    Args:
        tmp_path (Path): Temporary directory provided by pytest.

    Returns:
        TestClient: Configured client instance.
    """

    database_url = f"sqlite:///{tmp_path/'test.db'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, future=True)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    def override_get_settings() -> Settings:
        return Settings(
            data_dir=tmp_path / "data",
            database_url=database_url,
            storage_dir=tmp_path / "storage",
            allowed_image_extensions={"png"},
            upload_max_bytes=5000000,
            default_limit=10,
            default_offset=0,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    return TestClient(app)


def test_create_and_get_card(tmp_path):
    """
    Expected: create a card and fetch it back.
    """

    client = build_test_app(tmp_path)
    payload = {"set_code": "OP-05", "card_name": "Nami", "card_number": "OP05-100", "priority_manual": 1}
    create_res = client.post("/cards", json=payload)
    assert create_res.status_code == 201
    card_id = create_res.json()["id"]

    get_res = client.get(f"/cards/{card_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["card_name"] == "Nami"
    assert data["priority_manual"] == 1


def test_duplicate_card_rejected(tmp_path):
    """
    Failure: duplicates with same set/number/variant are rejected.
    """

    client = build_test_app(tmp_path)
    payload = {"set_code": "OP-05", "card_name": "Nami", "card_number": "OP05-100", "variant": "SP"}
    first = client.post("/cards", json=payload)
    assert first.status_code == 201
    duplicate = client.post("/cards", json=payload)
    assert duplicate.status_code == 400


def test_filtering_by_priority_and_search(tmp_path):
    """
    Edge: filtering returns only matching cards.
    """

    client = build_test_app(tmp_path)
    cards = [
        {"set_code": "OP-05", "card_name": "Nami", "card_number": "OP05-100", "priority_manual": 5},
        {"set_code": "OP-09", "card_name": "Shanks", "card_number": "OP09-001", "priority_manual": 15},
    ]
    for card in cards:
        assert client.post("/cards", json=card).status_code == 201

    res = client.get("/cards", params={"priority_max": 10, "search": "nami"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["card_name"] == "Nami"


def test_import_excel(tmp_path):
    """
    Expected: Excel import adds new cards.
    """

    client = build_test_app(tmp_path)
    df = pd.DataFrame(
        [
            {
                "Set": "OP-05",
                "Card": "Enel",
                "Card No.": "OP05-098",
                "Variant": "SP",
                "Strategy": "Invest",
                "Priority (1=Top)": 3,
                "Price Source": "PriceCharting",
                "Price": 127.5,
            }
        ]
    )
    excel_path = tmp_path / "sample.xlsx"
    df.to_excel(excel_path, index=False)

    with open(excel_path, "rb") as fp:
        res = client.post("/cards/import/excel", files={"file": ("sample.xlsx", fp, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert res.status_code == 200
    stats = res.json()
    assert stats["inserted"] == 1

    list_res = client.get("/cards")
    assert list_res.json()["total"] == 1


def test_list_sets(tmp_path):
    """
    Expected: sets endpoint returns distinct set codes.
    """

    client = build_test_app(tmp_path)
    cards = [
        {"set_code": "OP-05", "card_name": "Nami", "card_number": "OP05-100"},
        {"set_code": "OP-09", "card_name": "Shanks", "card_number": "OP09-001"},
        {"set_code": "OP-05", "card_name": "Enel", "card_number": "OP05-101"},
    ]
    for card in cards:
        assert client.post("/cards", json=card).status_code == 201

    res = client.get("/cards/sets")
    assert res.status_code == 200
    payload = res.json()
    assert payload["sets"] == ["OP-05", "OP-09"]


def test_import_all_sheets(tmp_path):
    """
    Expected: importing ALL sheets aggregates rows and dedupes identity.
    """

    client = build_test_app(tmp_path)
    sheet_a = pd.DataFrame(
        [
            {"Set": "S1", "Card": "Alpha", "Card No.": "S1-001", "Variant": "Base", "Priority (1=Top)": 1},
        ]
    )
    sheet_b = pd.DataFrame(
        [
            {"Set": "S2", "Card": "Beta", "Card No.": "S2-001", "Variant": "Base", "Priority (1=Top)": 2},
            {"Set": "S1", "Card": "Alpha", "Card No.": "S1-001", "Variant": "Base", "Priority (1=Top)": 3},
        ]
    )
    excel_path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(excel_path) as writer:
        sheet_a.to_excel(writer, sheet_name="A", index=False)
        sheet_b.to_excel(writer, sheet_name="B", index=False)

    with open(excel_path, "rb") as fp:
        res = client.post(
            "/cards/import/excel",
            data={"sheet_name": "ALL"},
            files={"file": ("multi.xlsx", fp, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert res.status_code == 200
    stats = res.json()
    assert stats["inserted"] == 2
    assert stats["updated"] == 1

    list_res = client.get("/cards")
    assert list_res.json()["total"] == 2


def test_market_sync_updates_price_and_image(tmp_path, monkeypatch):
    """
    Expected: market sync pulls price and image_url from provided link.
    """

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return """
            <html>
              <head>
                <meta property="og:image" content="https://example.com/image.jpg" />
                    <meta property="og:title" content="Enel [SP] OP05-100" />
              </head>
              <body>
                <span class="price">$127.50</span>
              </body>
            </html>
            """

    def fake_get(url, timeout=10.0, headers=None, follow_redirects=True):
        return DummyResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    client = build_test_app(tmp_path)
    payload = {"set_code": "OP-05", "card_name": "Enel", "card_number": "OP05-100"}
    card_id = client.post("/cards", json=payload).json()["id"]

    res = client.post(f"/cards/{card_id}/market-sync", params={"market_url": "https://example.com/enel"})
    assert res.status_code == 200
    data = res.json()
    assert data["price"] == 127.5
    assert data["image_url"] == "https://example.com/image.jpg"
    assert data["variant"] == "SP"
    assert data["language"] == "English"


def test_create_with_link_only(tmp_path, monkeypatch):
    """
    Link-only create should enrich required fields from market metadata.
    """

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return """
            <html>
              <head>
                <meta property="og:image" content="https://example.com/image.jpg" />
                <meta property="og:title" content="Enel [SP] OP05-100" />
              </head>
              <body>
                <span class="price">$127.50</span>
              </body>
            </html>
            """

    def fake_get(url, timeout=10.0, headers=None, follow_redirects=True):
        return DummyResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    client = build_test_app(tmp_path)
    payload = {"market_url": "https://example.com/enel"}
    res = client.post("/cards", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["card_name"] == "Enel"
    assert data["card_number"] == "OP05-100"
    assert data["set_code"] == "OP-05"
    assert data["variant"] == "SP"
    assert data["language"] == "English"


def test_language_detection_japanese(tmp_path, monkeypatch):
    """
    Language should be Japanese when URL contains 'japanese'.
    """

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return """
            <html>
              <head>
                <meta property="og:image" content="https://example.com/image.jpg" />
                <meta property="og:title" content="Monkey.D.Luffy [Alt Art] OP01-003" />
              </head>
              <body>
                <span class="price">$61.00</span>
              </body>
            </html>
            """

    def fake_get(url, timeout=10.0, headers=None, follow_redirects=True):
        return DummyResponse()

    monkeypatch.setattr(httpx, "get", fake_get)

    client = build_test_app(tmp_path)
    payload = {"market_url": "https://www.pricecharting.com/game/one-piece-japanese-romance-dawn/monkeydluffy-alt-art-op01-003"}
    res = client.post("/cards", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["language"] == "Japanese"


def test_rarity_mapping_and_value_score(tmp_path):
    """
    Rarity should autopopulate from variant/scarcity mapping and value_score should compute.
    
    Rarity Table:
      - Manga -> 1 (forced bottom)
      - Leader SP -> 95
      - SP -> 90
      - Anniversary -> 85
      - Wanted Poster / WP -> 80
      - Alt Art Leader -> 78
      - Alt Art / Alternate Art / Full Art / AA -> 70
      - Alt Art DON!! -> 65
      - Promo / Stamped / Event -> 68
      - Secret Rare / SEC -> 55
      - Default -> 40
    """

    client = build_test_app(tmp_path)
    
    # Test cases: (variant, scarcity, expected_rarity, description)
    test_cases = [
        # SP variant = 90
        ("SP", None, 90, "SP variant"),
        ("sp", None, 90, "SP lowercase"),
        
        # Manga = 1 (forced bottom)
        ("Manga", None, 1, "Manga forced bottom"),
        
        # Alt Art variants = 70 (MUST NOT be overridden by scarcity containing SP)
        ("Alternate Art", None, 70, "Alternate Art"),
        ("Alt Art", None, 70, "Alt Art"),
        ("Full Art", None, 70, "Full Art"),
        ("Alternate Art", "~1 per case (SP)", 70, "Alt Art with SP scarcity - variant takes precedence"),
        ("Alt Art", "SP rarity", 70, "Alt Art with SP in scarcity - variant takes precedence"),
        
        # Alt Art Leader = 78
        ("Alternate Art (Leader)", None, 78, "Alternate Art Leader"),
        ("Alt Art Leader", None, 78, "Alt Art Leader"),
        
        # Wanted Poster / WP = 80
        ("Wanted Poster", None, 80, "Wanted Poster"),
        ("WP", None, 80, "WP abbreviation"),
        
        # Anniversary = 85
        ("Anniversary", None, 85, "Anniversary"),
        
        # Secret Rare = 55
        ("Secret Rare", None, 55, "Secret Rare"),
        
        # Promo / Stamped / Event = 68
        ("Promo", None, 68, "Promo"),
        ("Stamped", None, 68, "Stamped"),
        ("Event", None, 68, "Event"),
        
        # Default = 40
        ("Base", None, 40, "Default/Base"),
        ("", None, 40, "Empty variant"),
    ]
    
    for i, (variant, scarcity, expected_rarity, desc) in enumerate(test_cases):
        payload = {
            "set_code": "TEST",
            "card_name": f"Test Card {i}",
            "card_number": f"TEST-{i:03d}",
            "variant": variant or "Base",
            "scarcity": scarcity,
            "price": 100.0,
        }
        res = client.post("/cards", json=payload)
        assert res.status_code == 201, f"Failed to create card for: {desc}"
        data = res.json()
        assert data["rarity_score"] == float(expected_rarity), f"Rarity mismatch for '{desc}': expected {expected_rarity}, got {data['rarity_score']}"
    
    # Test value_score computation (rarity/price)
    payload_value = {
        "set_code": "VAL",
        "card_name": "Value Test",
        "card_number": "VAL-001",
        "variant": "SP",
        "price": 100.0,
    }
    res_value = client.post("/cards", json=payload_value)
    assert res_value.status_code == 201
    data_value = res_value.json()
    assert data_value["rarity_score"] == 90.0
    assert data_value["value_score"] == 0.9  # 90/100 = 0.9

