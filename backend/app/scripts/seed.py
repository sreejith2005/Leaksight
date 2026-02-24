"""
LeakSight V1 — Seed Script

Source: docs/DATABASE_SCHEMA.md (Sections 3.5, 3.6, 3.17)
        LeakSight Infra Guide V2.md (Section 8.3)

Idempotent seed script that populates:
  1. canonical_units (11 units across 5 dimensions)
  2. unit_conversion_factors (system defaults, tenant_id=NULL)

Uses INSERT ... ON CONFLICT DO NOTHING so it can be run multiple times safely.

Usage:
  docker compose exec backend python -m app.scripts.seed
"""

import asyncio
import sys
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.app.core.config import get_settings


# ============================================================
# Canonical Units — 11 units across 5 dimensions
# Source: docs/DATABASE_SCHEMA.md Section 3.5
# ============================================================
CANONICAL_UNITS = [
    # WEIGHT
    {"name": "metric_ton", "symbol": "MT", "dimension": "WEIGHT"},
    {"name": "kilogram", "symbol": "KG", "dimension": "WEIGHT"},
    {"name": "gram", "symbol": "G", "dimension": "WEIGHT"},
    # VOLUME
    {"name": "litre", "symbol": "L", "dimension": "VOLUME"},
    {"name": "millilitre", "symbol": "ML", "dimension": "VOLUME"},
    # COUNT
    {"name": "nos", "symbol": "Nos", "dimension": "COUNT"},
    {"name": "box", "symbol": "Box", "dimension": "COUNT"},
    {"name": "set", "symbol": "Set", "dimension": "COUNT"},
    # AREA
    {"name": "square_foot", "symbol": "Sqft", "dimension": "AREA"},
    {"name": "square_metre", "symbol": "Sqm", "dimension": "AREA"},
    # LENGTH
    {"name": "running_metre", "symbol": "RMT", "dimension": "LENGTH"},
]

# ============================================================
# Unit Conversion Factors — system defaults (tenant_id = NULL)
# Source: docs/DATABASE_SCHEMA.md Section 3.6
#
# Each pair is stored as (from → to, factor) and (to → from, 1/factor)
# ============================================================
UNIT_CONVERSIONS = [
    # WEIGHT conversions
    ("MT", "KG", Decimal("1000")),
    ("MT", "G", Decimal("1000000")),
    ("KG", "G", Decimal("1000")),
    # VOLUME conversions
    ("L", "ML", Decimal("1000")),
    # AREA conversions
    ("Sqm", "Sqft", Decimal("10.7639104167")),
]


async def seed_canonical_units(session: AsyncSession) -> dict[str, str]:
    """Seed canonical_units table. Returns symbol→id mapping.

    Uses INSERT ON CONFLICT DO NOTHING for idempotency.
    """
    symbol_to_id: dict[str, str] = {}

    for unit in CANONICAL_UNITS:
        unit_id = str(uuid.uuid4())
        result = await session.execute(
            text("""
                INSERT INTO canonical_units (id, name, symbol, dimension)
                VALUES (:id, :name, :symbol, :dimension)
                ON CONFLICT (name) DO NOTHING
                RETURNING id
            """),
            {"id": unit_id, "name": unit["name"], "symbol": unit["symbol"], "dimension": unit["dimension"]},
        )
        row = result.fetchone()
        if row:
            # Newly inserted
            symbol_to_id[unit["symbol"]] = str(row[0])
        else:
            # Already existed — fetch existing id
            existing = await session.execute(
                text("SELECT id FROM canonical_units WHERE name = :name"),
                {"name": unit["name"]},
            )
            existing_row = existing.fetchone()
            if existing_row:
                symbol_to_id[unit["symbol"]] = str(existing_row[0])

    return symbol_to_id


async def seed_conversion_factors(
    session: AsyncSession, symbol_to_id: dict[str, str]
) -> None:
    """Seed unit_conversion_factors table with system defaults.

    For each conversion pair (A→B, factor), also inserts the inverse (B→A, 1/factor).
    Uses INSERT ON CONFLICT DO NOTHING for idempotency.
    """
    for from_symbol, to_symbol, factor in UNIT_CONVERSIONS:
        from_id = symbol_to_id.get(from_symbol)
        to_id = symbol_to_id.get(to_symbol)

        if not from_id or not to_id:
            print(f"  WARNING: Skipping {from_symbol}→{to_symbol} — unit not found")
            continue

        # Forward conversion
        await session.execute(
            text("""
                INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
                VALUES (:id, :from_id, :to_id, :factor, NULL)
                ON CONFLICT (from_unit_id, to_unit_id, tenant_id) DO NOTHING
            """),
            {
                "id": str(uuid.uuid4()),
                "from_id": from_id,
                "to_id": to_id,
                "factor": str(factor),
            },
        )

        # Inverse conversion
        inverse_factor = Decimal("1") / factor
        await session.execute(
            text("""
                INSERT INTO unit_conversion_factors (id, from_unit_id, to_unit_id, factor, tenant_id)
                VALUES (:id, :from_id, :to_id, :factor, NULL)
                ON CONFLICT (from_unit_id, to_unit_id, tenant_id) DO NOTHING
            """),
            {
                "id": str(uuid.uuid4()),
                "from_id": to_id,
                "to_id": from_id,
                "factor": str(inverse_factor),
            },
        )


async def run_seed() -> None:
    """Main seed function. Creates engine, seeds all tables."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        async with session.begin():
            print("LeakSight V1 — Seeding system data...")
            print()

            # 1. Canonical Units
            print("  [1/2] Seeding canonical_units (11 units, 5 dimensions)...")
            symbol_to_id = await seed_canonical_units(session)
            print(f"        → {len(symbol_to_id)} units ready")

            # 2. Conversion Factors
            print("  [2/2] Seeding unit_conversion_factors (system defaults)...")
            await seed_conversion_factors(session, symbol_to_id)

            # Count conversions
            result = await session.execute(
                text("SELECT count(*) FROM unit_conversion_factors WHERE tenant_id IS NULL")
            )
            count = result.scalar()
            print(f"        → {count} conversion factors ready")

            print()
            print("Seed complete. All operations are idempotent — safe to run again.")

    await engine.dispose()


def main() -> None:
    """Entry point for `python -m app.scripts.seed`."""
    try:
        asyncio.run(run_seed())
    except Exception as e:
        print(f"ERROR: Seed failed — {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
