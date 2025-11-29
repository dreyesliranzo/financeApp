import os
from pathlib import Path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    BASE_DIR = Path(__file__).resolve().parent
    DB_PATH = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'finance.db'}")
    SQLALCHEMY_DATABASE_URI = DB_PATH
    SQLALCHEMY_TRACK_MODIFICATIONS = False
