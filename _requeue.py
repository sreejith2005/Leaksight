"""Re-queue pending documents for parsing."""
import asyncio
import sys
sys.path.insert(0, '.')

from backend.app.core.database import async_session_factory
from backend.app.tasks.parse_task import parse_document
from sqlalchemy import text

async def list_docs():
    async with async_session_factory() as db:
        result = await db.execute(text("SELECT id, tenant_id, file_path, parse_status, doc_type FROM documents ORDER BY created_at"))
        rows = result.fetchall()
        for r in rows:
            print(f"  {r[0]} | {r[3]:8s} | {r[4]:8s} | {r[2]}")
        return rows

rows = asyncio.run(list_docs())
print(f"\nFound {len(rows)} documents. Re-queuing PENDING ones...")

for r in rows:
    doc_id, tenant_id, file_path, parse_status, doc_type = r
    if parse_status == 'PENDING':
        parse_document.delay(str(doc_id), str(tenant_id))
        print(f"  Queued: {doc_id}")

print("Done.")
