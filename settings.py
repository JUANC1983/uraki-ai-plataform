# config/settings.py
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "URAKI AI Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # -------------------------------------------------------------------------
    # SECRET_KEY — no default intentionally.
    # Must be set via SECRET_KEY env var or .env file.
    # The application will refuse to start if this is missing or too short.
    # Generate a safe value with: python -c "import secrets; print(secrets.token_hex(32))"
    # -------------------------------------------------------------------------
    SECRET_KEY: str = ""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://uraki:uraki_pass@localhost:5432/uraki_db"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis (optional — recommended for rate limiting in production)
    REDIS_URL: Optional[str] = None

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # JWT Auth
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS — comma-separated string of allowed origins.
    # Set via ALLOWED_ORIGINS env var, e.g.:
    #   ALLOWED_ORIGINS=https://app.uraki.co,https://dashboard.uraki.co
    # Dev default permits localhost dashboards only.
    # Use get_allowed_origins() to obtain the parsed list.
    ALLOWED_ORIGINS: str = (
        "http://localhost:3000,"
        "http://localhost:8501,"
        "http://localhost:8502,"
        "http://127.0.0.1:8501,"
        "http://127.0.0.1:8502"
    )

    def get_allowed_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS into a list. Use this in main.py CORS config."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    # File Storage
    STORAGE_BACKEND: str = "local"  # local | s3
    LOCAL_STORAGE_PATH: str = "./storage"
    S3_BUCKET: Optional[str] = None
    S3_REGION: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # Vector Store
    VECTOR_STORE_BACKEND: str = "pgvector"  # pgvector | pinecone
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX: Optional[str] = None

    # Audit
    AUDIT_LOG_TO_DB: bool = True
    AUDIT_LOG_TO_FILE: bool = True
    AUDIT_LOG_FILE: str = "./logs/audit.jsonl"

    # Streamlit Dashboard
    DASHBOARD_HOST: str = "0.0.0.0"
    DASHBOARD_PORT: int = 8501
    API_BASE_URL: str = "http://localhost:8000"

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------



# Known insecure placeholder values — rejected at startup (not at import time,
# so validate.py and demo.py can still import settings without crashing).
_INSECURE_KEY_SENTINELS: frozenset[str] = frozenset({
    "",
    "change-me-in-production-min-32-chars-long",
    "secret",
    "your-secret-key",
})

_MIN_KEY_LENGTH = 32


def validate_secret_key(secret_key: str) -> None:
    """
    Call once at application startup (lifespan).
    Raises RuntimeError with a clear message if the key is insecure.
    """
    if secret_key in _INSECURE_KEY_SENTINELS or len(secret_key) < _MIN_KEY_LENGTH:
        raise RuntimeError(
            "\n"
            "URAKI -- STARTUP BLOCKED\n"
            "SECRET_KEY is missing or too short (minimum 32 characters).\n"
            "\n"
            "Generate a secure key:\n"
            "  python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "\n"
            "Then add to your .env file:\n"
            "  SECRET_KEY=<generated_value>\n"
        )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
