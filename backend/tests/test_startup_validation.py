"""
LeakSight V1 — Startup Validation Tests

Source: Phase 11.1 — Environment Configuration Audit

Verifies:
  - validate_production_settings raises EnvironmentError on missing SECRET_KEY
  - validate_production_settings raises EnvironmentError on missing POSTGRES_PASSWORD
  - validate_production_settings raises EnvironmentError on insecure ALLOWED_HOSTS in production
  - validate_production_settings raises EnvironmentError on missing SMTP credentials in production
  - validate_production_settings passes with valid production configuration
  - validate_production_settings passes in development mode with relaxed checks
"""

import pytest

from backend.app.core.config import Settings, validate_production_settings


class TestStartupValidation:
    """Tests for the startup validation function added in Phase 11.1."""

    def test_raises_on_placeholder_secret_key(self):
        """SECRET_KEY set to placeholder default must raise EnvironmentError."""
        settings = Settings(
            secret_key="CHANGE_ME_GENERATE_A_REAL_SECRET",
            postgres_password="a_real_password_here",
            app_env="development",
        )
        with pytest.raises(EnvironmentError, match="SECRET_KEY"):
            validate_production_settings(settings)

    def test_raises_on_empty_secret_key(self):
        """Empty SECRET_KEY must raise EnvironmentError."""
        settings = Settings(
            secret_key="",
            postgres_password="a_real_password_here",
            app_env="development",
        )
        with pytest.raises(EnvironmentError, match="SECRET_KEY"):
            validate_production_settings(settings)

    def test_raises_on_placeholder_postgres_password(self):
        """POSTGRES_PASSWORD set to placeholder default must raise EnvironmentError."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="CHANGE_ME_STRONG_PASSWORD",
            app_env="development",
        )
        with pytest.raises(EnvironmentError, match="POSTGRES_PASSWORD"):
            validate_production_settings(settings)

    def test_raises_on_empty_postgres_password(self):
        """Empty POSTGRES_PASSWORD must raise EnvironmentError."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="",
            app_env="development",
        )
        with pytest.raises(EnvironmentError, match="POSTGRES_PASSWORD"):
            validate_production_settings(settings)

    def test_raises_on_localhost_allowed_hosts_in_production(self):
        """ALLOWED_HOSTS=localhost in production must raise EnvironmentError."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="a" * 64,
            app_env="production",
            allowed_hosts="localhost",
            smtp_user="user@test.com",
            smtp_password="smtp_key_123",
        )
        with pytest.raises(EnvironmentError, match="ALLOWED_HOSTS"):
            validate_production_settings(settings)

    def test_raises_on_wildcard_allowed_hosts_in_production(self):
        """ALLOWED_HOSTS=* in production must raise EnvironmentError."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="a" * 64,
            app_env="production",
            allowed_hosts="*",
            smtp_user="user@test.com",
            smtp_password="smtp_key_123",
        )
        with pytest.raises(EnvironmentError, match="ALLOWED_HOSTS"):
            validate_production_settings(settings)

    def test_raises_on_missing_smtp_user_in_production(self):
        """Missing SMTP_USER in production must raise EnvironmentError."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="a" * 64,
            app_env="production",
            allowed_hosts="app.leaksight.com",
            smtp_user="",
            smtp_password="smtp_key_123",
        )
        with pytest.raises(EnvironmentError, match="SMTP_USER"):
            validate_production_settings(settings)

    def test_raises_on_missing_smtp_password_in_production(self):
        """Missing SMTP_PASSWORD in production must raise EnvironmentError."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="a" * 64,
            app_env="production",
            allowed_hosts="app.leaksight.com",
            smtp_user="user@test.com",
            smtp_password="",
        )
        with pytest.raises(EnvironmentError, match="SMTP_PASSWORD"):
            validate_production_settings(settings)

    def test_raises_multiple_errors_at_once(self):
        """Multiple configuration errors must be reported in a single message."""
        settings = Settings(
            secret_key="CHANGE_ME_GENERATE_A_REAL_SECRET",
            postgres_password="CHANGE_ME_STRONG_PASSWORD",
            app_env="production",
            allowed_hosts="localhost",
            smtp_user="",
            smtp_password="",
        )
        with pytest.raises(EnvironmentError) as exc_info:
            validate_production_settings(settings)
        error_msg = str(exc_info.value)
        assert "SECRET_KEY" in error_msg
        assert "POSTGRES_PASSWORD" in error_msg
        assert "ALLOWED_HOSTS" in error_msg
        assert "SMTP_USER" in error_msg
        assert "SMTP_PASSWORD" in error_msg

    def test_passes_with_valid_production_config(self):
        """Valid production configuration must not raise."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="a" * 64,
            app_env="production",
            allowed_hosts="app.leaksight.com",
            smtp_user="user@brevo.com",
            smtp_password="xkeysib-abc123",
        )
        # Should not raise
        validate_production_settings(settings)

    def test_passes_in_development_without_smtp(self):
        """Development mode should not require SMTP credentials."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="a" * 64,
            app_env="development",
            allowed_hosts="localhost",
            smtp_user="",
            smtp_password="",
        )
        # Should not raise — SMTP only required in production
        validate_production_settings(settings)

    def test_passes_in_staging_without_smtp(self):
        """Staging mode should not require SMTP credentials."""
        settings = Settings(
            secret_key="a" * 128,
            postgres_password="a" * 64,
            app_env="staging",
            allowed_hosts="staging.leaksight.com",
            smtp_user="",
            smtp_password="",
        )
        # Should not raise — SMTP only required in production
        validate_production_settings(settings)

    def test_raises_on_invalid_app_env(self):
        """Invalid APP_ENV value must raise EnvironmentError."""
        # Pydantic will reject invalid Literal values, but if we bypass
        # validation, the startup check should also catch it.
        # Since Pydantic Literal enforces valid values, we test the function
        # directly with a mocked settings object.
        class MockSettings:
            app_env = "invalid_env"
            secret_key = "a" * 128
            postgres_password = "a" * 64
            allowed_hosts = "app.leaksight.com"
            smtp_user = "user@test.com"
            smtp_password = "key123"

        with pytest.raises(EnvironmentError, match="APP_ENV"):
            validate_production_settings(MockSettings())
