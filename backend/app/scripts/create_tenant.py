"""
LeakSight V1 — Create Tenant Script

Source: docs/DATABASE_SCHEMA.md (Sections 3.1, 3.2, 3.17)
        LeakSight Infra Guide V2.md (Section 16, item "New tenant in under 5 minutes")

CLI script to create a new tenant with:
  - Tenant record (tenants table)
  - Tenant settings with LeakSight defaults (tenant_settings table)
  - Admin user with a temporary random password (users table)

Usage:
  docker compose exec backend python -m app.scripts.create_tenant \
      --name "Pilot Client" --email "admin@client.com"
"""

import argparse
import asyncio
import secrets
import sys
import uuid

from passlib.hash import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.app.core.config import get_settings
from backend.app.models.tenant import DEFAULT_ABBREVIATION_DICTIONARY

# Default tenant settings — matches DATABASE_SCHEMA.md Section 3.17
DEFAULT_SETTINGS = {
    "fuzzy_threshold": 0.85,
    "duplicate_window_days": 30,
    "manual_review_threshold": 0.70,
    "base_currency": "INR",
}


def generate_temp_password(length: int = 16) -> str:
    """Generate a cryptographically secure temporary password.

    Returns a URL-safe random string of the specified length.
    """
    return secrets.token_urlsafe(length)


async def create_tenant(
    name: str,
    admin_email: str,
) -> dict:
    """Create a new tenant with settings and admin user.

    Args:
        name: Tenant display name.
        admin_email: Email for the initial admin user.

    Returns:
        Dict with tenant_id, name, admin_email, temp_password.

    Raises:
        RuntimeError: If tenant or user creation fails.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    temp_password = generate_temp_password()
    password_hash = bcrypt.hash(temp_password)

    async with session_factory() as session:
        async with session.begin():
            # 1. Create tenant
            await session.execute(
                text("""
                    INSERT INTO tenants (id, name, is_active)
                    VALUES (:id, :name, true)
                """),
                {"id": tenant_id, "name": name},
            )

            # 2. Create tenant settings with defaults
            import json
            await session.execute(
                text("""
                    INSERT INTO tenant_settings (
                        tenant_id, abbreviation_dictionary,
                        fuzzy_threshold, duplicate_window_days,
                        manual_review_threshold, base_currency
                    )
                    VALUES (
                        :tenant_id, CAST(:abbrev_dict AS jsonb),
                        :fuzzy, :dup_window,
                        :review_threshold, :base_currency
                    )
                """),
                {
                    "tenant_id": tenant_id,
                    "abbrev_dict": json.dumps(DEFAULT_ABBREVIATION_DICTIONARY),
                    "fuzzy": DEFAULT_SETTINGS["fuzzy_threshold"],
                    "dup_window": DEFAULT_SETTINGS["duplicate_window_days"],
                    "review_threshold": DEFAULT_SETTINGS["manual_review_threshold"],
                    "base_currency": DEFAULT_SETTINGS["base_currency"],
                },
            )

            # 3. Create admin user
            await session.execute(
                text("""
                    INSERT INTO users (id, tenant_id, email, password_hash, role, is_active)
                    VALUES (:id, :tenant_id, :email, :password_hash, 'ADMIN', true)
                """),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "email": admin_email,
                    "password_hash": password_hash,
                },
            )

    await engine.dispose()

    return {
        "tenant_id": tenant_id,
        "name": name,
        "admin_email": admin_email,
        "temp_password": temp_password,
    }


def main() -> None:
    """CLI entry point for `python -m app.scripts.create_tenant`."""
    parser = argparse.ArgumentParser(
        description="Create a new LeakSight tenant with admin user."
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Tenant display name (e.g., 'Pilot Client')",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Admin user email address",
    )
    args = parser.parse_args()

    if not args.name.strip():
        print("ERROR: --name cannot be empty", file=sys.stderr)
        sys.exit(1)

    if "@" not in args.email or "." not in args.email:
        print("ERROR: --email must be a valid email address", file=sys.stderr)
        sys.exit(1)

    try:
        result = asyncio.run(create_tenant(args.name.strip(), args.email.strip()))
    except Exception as e:
        print(f"ERROR: Tenant creation failed — {e}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Tenant created:")
    print(f"  Tenant ID:     {result['tenant_id']}")
    print(f"  Name:          {result['name']}")
    print(f"  Admin email:   {result['admin_email']}")
    print(f"  Temp password: {result['temp_password']}")
    print()
    print("⚠ Share this password securely. User must change it on first login.")


if __name__ == "__main__":
    main()
