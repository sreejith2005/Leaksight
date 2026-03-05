"""Manually trigger normalize for the invoice raw_parse."""
import sys
sys.path.insert(0, '.')
from backend.app.tasks.normalize_task import normalize_document

# Invoice raw_parse_id and tenant_id from our DB check
raw_parse_id = "08034217-2913-48a2-bb59-50a5e1cf6ebb"
tenant_id = "edeb6d4c-6b06-4909-9bf2-f97ef0a149c8"

# First, clear the failure flag
import asyncio
from backend.app.core.database import async_session_factory
from sqlalchemy import text

async def clear_flag():
    async with async_session_factory() as db:
        await db.execute(text(f"UPDATE raw_parses SET failure_flags = '[]'::jsonb WHERE id = '{raw_parse_id}'"))
        await db.commit()
        print("Cleared failure flags")

asyncio.run(clear_flag())

# Dispatch the normalize task
normalize_document.delay(raw_parse_id, tenant_id)
print(f"Dispatched normalize task for raw_parse={raw_parse_id}")
