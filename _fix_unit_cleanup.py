import asyncio
import re
from uuid import UUID

from sqlalchemy import select, text

from backend.app.core.database import async_session_factory
from backend.app.tools.contract_structuring.models import ExtractedLineItem


TENANT_ID = UUID("edeb6d4c-6b06-4909-9bf2-f97ef0a149c8")


def is_year_like(value: str) -> bool:
    if not value:
        return False
    cleaned = value.replace(",", "").replace(" ", "").strip()
    if re.match(r"^\d{4}$", cleaned):
        year = int(cleaned)
        return 1900 <= year <= 2100
    return False


async def main() -> None:
    async with async_session_factory() as db:
        await db.execute(text(f"SET LOCAL app.current_tenant_id = '{TENANT_ID}'"))

        rows = list(
            (
                await db.execute(
                    select(ExtractedLineItem).where(
                        ExtractedLineItem.tenant_id == TENANT_ID,
                        ExtractedLineItem.unit_raw.is_not(None),
                    )
                )
            ).scalars()
        )

        updated = 0
        for row in rows:
            value = (row.unit_raw or "").strip()
            if is_year_like(value):
                row.unit_raw = None
                row.unit_confidence = 0.0
                row.needs_review = True
                updated += 1

        await db.commit()

    print(f"Updated {updated} rows: unit_raw cleared where value was year-like")


if __name__ == "__main__":
    asyncio.run(main())