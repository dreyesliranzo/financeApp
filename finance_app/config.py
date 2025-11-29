import os
from pathlib import Path
from urllib.parse import urlparse


def normalize_db_url(url: str) -> str:
    """Ensure SQLAlchemy-compatible Postgres URL and add SSL only when needed."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)

    parsed = urlparse(url)
    host = parsed.hostname or ""
    is_internal = "internal" in host  # Render internal URLs should not force sslmode=require

    if url.startswith("postgresql") and "sslmode=" not in url and not is_internal:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    BASE_DIR = Path(__file__).resolve().parent
    raw_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'finance.db'}")
    DB_PATH = normalize_db_url(raw_url)
    SQLALCHEMY_DATABASE_URI = DB_PATH
    SQLALCHEMY_TRACK_MODIFICATIONS = False
