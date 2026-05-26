"""
LeakSight V1 — Application Configuration

Source: .env.example, docs/ARCHITECTURE.md, docs/CLAUDE.md

All configuration is loaded from environment variables via Pydantic Settings.
No hardcoded secrets. No defaults for sensitive values in production.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: navigate from core/config.py → core → app → backend → root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All sensitive values (SECRET_KEY, POSTGRES_PASSWORD, SMTP_PASSWORD)
    must be provided via .env file or environment variables.
    No defaults are acceptable for production secrets.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: Literal["development", "staging", "production"] = "development"
    secret_key: str = "CHANGE_ME_GENERATE_A_REAL_SECRET"
    allowed_hosts: str = "localhost"

    # --- Database (PostgreSQL 15) ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "leaksight"
    postgres_user: str = "leaksight_user"
    postgres_password: str = "CHANGE_ME_STRONG_PASSWORD"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Celery ---
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Document Storage ---
    document_storage_path: str = "/app/data/documents"
    max_upload_size_mb: int = 200

    # --- SMTP ---
    smtp_host: str = "smtp-relay.brevo.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@localhost"

    # --- Tenant Default Settings ---
    default_fuzzy_threshold: float = 0.85
    default_duplicate_window_days: int = 30
    default_manual_review_threshold: float = 0.70
    default_base_currency: str = "INR"

    @property
    def database_url(self) -> str:
        """Construct async PostgreSQL connection URL for SQLAlchemy.

        Returns:
            Async-compatible PostgreSQL URL using asyncpg driver.
        """
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Construct sync PostgreSQL connection URL (for Alembic migrations).

        Returns:
            Sync-compatible PostgreSQL URL using psycopg2 driver.
        """
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @field_validator("default_fuzzy_threshold", "default_manual_review_threshold")
    @classmethod
    def validate_threshold_range(cls, v: float) -> float:
        """Ensure threshold values are in valid range [0.0, 1.0]."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Threshold must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("max_upload_size_mb")
    @classmethod
    def validate_max_upload_size(cls, v: int) -> int:
        """Ensure max upload size is positive and reasonable."""
        if v <= 0:
            raise ValueError(f"Max upload size must be positive, got {v}")
        return v


def validate_production_settings(settings: "Settings") -> None:
    """Validate that all required production settings are securely configured.

    Called during application startup. Raises EnvironmentError with a specific
    message if any required secret is missing, insecure, or if APP_ENV is invalid.

    This prevents silent misconfiguration — the application will not start
    if secrets are set to their placeholder defaults.

    Args:
        settings: The loaded application settings to validate.

    Raises:
        EnvironmentError: If any required secret is missing or insecure.
    """
    errors: list[str] = []

    # Validate APP_ENV is an accepted value
    valid_envs = ("production", "staging", "development")
    if settings.app_env not in valid_envs:
        errors.append(
            f"APP_ENV must be one of {valid_envs}, got '{settings.app_env}'"
        )

    # Validate SECRET_KEY is not the placeholder default
    if settings.secret_key in ("CHANGE_ME_GENERATE_A_REAL_SECRET", ""):
        errors.append(
            "SECRET_KEY is not set or uses the placeholder default. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(64))\""
        )

    # Validate POSTGRES_PASSWORD is not the placeholder default
    if settings.postgres_password in ("CHANGE_ME_STRONG_PASSWORD", ""):
        errors.append(
            "POSTGRES_PASSWORD is not set or uses the placeholder default. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # In production, enforce stricter checks
    if settings.app_env == "production":
        # ALLOWED_HOSTS must not be localhost or wildcard
        if settings.allowed_hosts in ("localhost", "*", ""):
            errors.append(
                "ALLOWED_HOSTS must be set to the actual domain in production, "
                f"got '{settings.allowed_hosts}'"
            )

        # SMTP credentials are required for notifications in production
        if not settings.smtp_user:
            errors.append(
                "SMTP_USER is required in production for email notifications"
            )
        if not settings.smtp_password:
            errors.append(
                "SMTP_PASSWORD is required in production for email notifications"
            )

    if errors:
        error_msg = "LeakSight startup configuration errors:\n" + "\n".join(
            f"  - {e}" for e in errors
        )
        raise EnvironmentError(error_msg)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings singleton.

    Returns:
        Application settings loaded from environment.
    """
    return Settings()
