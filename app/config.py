import os
from datetime import timedelta
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _database_uri() -> str:
    """
    Local dev: no DB_HOST set -> falls back to DATABASE_URL (sqlite by default).
    Deployment: set DB_HOST (+ DB_NAME, DB_USER, DB_PASSWORD, DB_PORT) and a
    PostgreSQL URI is built from them instead.
    """
    db_host = os.environ.get("DB_HOST")
    if not db_host:
        return os.environ.get("DATABASE_URL", "sqlite:///eva.db")

    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "eva")
    db_user = os.environ.get("DB_USER", "postgres")
    db_password = quote_plus(os.environ.get("DB_PASSWORD", ""))
    return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


class Config:
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FILE = os.environ.get("LOG_FILE", os.path.join(_ROOT, "logFile.log"))

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"

    MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "mqtt.eva.ai")
    MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", 8883))

    RATELIMIT_STORAGE_URL = os.environ.get("REDIS_URL", "memory://")

    # Google Gemini (via its OpenAI-compatible endpoint) — free tier
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

    # Deepgram STT
    DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")

    # S3 (TTS file storage)
    S3_BUCKET = os.environ.get("S3_BUCKET", "")
    S3_REGION = os.environ.get("S3_REGION", "ap-south-1")
    S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
    S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
    S3_PUBLIC_URL = os.environ.get("S3_PUBLIC_URL", "")  # CloudFront / custom domain
