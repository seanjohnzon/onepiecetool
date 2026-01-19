from pathlib import Path
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings
from .database import engine, init_database
from .models import Base
from .routers import cards, scheduler


# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="One Piece TCG Tracker", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/media", StaticFiles(directory=str(BASE_DIR.parent / "storage")), name="media")
app.include_router(cards.router)
app.include_router(scheduler.router)


@app.on_event("startup")
def on_startup() -> None:
    """
    Initialize database tables on startup.
    """

    Base.metadata.create_all(bind=engine)
    init_database()


@app.get("/health", response_class=HTMLResponse)
def health() -> str:
    """
    Health check endpoint.

    Returns:
        str: Simple health response.
    """

    return "ok"


@app.get("/", response_class=HTMLResponse)
def index(request: Request, settings: Settings = Depends(get_settings)) -> HTMLResponse:
    """
    Render the cards dashboard shell; data is fetched client-side.

    Args:
        request (Request): Incoming request.
        settings (Settings): Application settings dependency.

    Returns:
        HTMLResponse: Rendered HTML page.
    """

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "One Piece TCG Tracker",
            "default_limit": settings.default_limit,
        },
    )

