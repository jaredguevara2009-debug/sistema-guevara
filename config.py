import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE = (BASE_DIR / "instance" / "repuestos_guevara.db").as_posix()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 8 * 1024 * 1024))
    UPLOAD_FOLDER = BASE_DIR / "app" / "static" / "uploads" / "products"
    BUSINESS_NAME = os.getenv("BUSINESS_NAME", "REPUESTOS GUEVARA")
    BUSINESS_PHONE = os.getenv("BUSINESS_PHONE", "")
    BUSINESS_ADDRESS = os.getenv("BUSINESS_ADDRESS", "")
    TIMEZONE = os.getenv("TIMEZONE", "America/La_Paz")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    REMEMBER_COOKIE_HTTPONLY = True

