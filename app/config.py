import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///eva.db")
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

    # Azure OpenAI (GPT-4.1)
    AZURE_ENDPOINT = os.environ.get("AZURE_ENDPOINT", "https://models.github.ai/inference")
    AZURE_MODEL = os.environ.get("AZURE_MODEL", "openai/gpt-4.1")
    AZURE_TOKEN = os.environ.get("GITHUB_TOKEN", "")

    # S3
    S3_BUCKET = os.environ.get("S3_BUCKET", "")
    S3_REGION = os.environ.get("S3_REGION", "ap-south-1")
    S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
    S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
    S3_PUBLIC_URL = os.environ.get("S3_PUBLIC_URL", "")  # CloudFront / custom domain

    # Whisper (STT)
    WHISPER_BIN = os.environ.get(
        "WHISPER_BIN", os.path.join(_ROOT, "build", "bin", "whisper-cli")
    )
    WHISPER_MODEL = os.environ.get(
        "WHISPER_MODEL", os.path.join(_ROOT, "models", "ggml-tiny.bin")
    )
