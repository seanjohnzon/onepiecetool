from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel, ConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    """
    Application configuration.

    Attributes:
        database_url (str): Connection URL for the SQLite database.
        storage_dir (Path): Directory for storing uploaded card images.
        allowed_image_extensions (set[str]): Whitelisted image file extensions.
        upload_max_bytes (int): Maximum allowed upload size for images.
        default_limit (int): Default page size for list endpoints.
        default_offset (int): Default offset for pagination.
    """

    data_dir: Path = BASE_DIR / "data"
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'cards.db')}"
    storage_dir: Path = BASE_DIR / "storage" / "cards"
    allowed_image_extensions: set[str] = {"jpg", "jpeg", "png", "webp"}
    upload_max_bytes: int = 5 * 1024 * 1024
    default_limit: int = 50
    default_offset: int = 0
    default_language: str = "English"

    model_config = ConfigDict(arbitrary_types_allowed=True)


@lru_cache
def get_settings() -> Settings:
    """
    Return cached application settings and ensure necessary directories exist.

    Returns:
        Settings: The application settings instance.
    """

    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings

