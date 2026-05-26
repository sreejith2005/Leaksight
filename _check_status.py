import asyncio, sys
sys.path.insert(0, '.')
from backend.app.core.database import async_session_factory
from sqlalchemy import text

async def check():
    async with async_session_factory() as db:
        print("=== Documents ===")
        result = await db.execute(text("SELECT id, parse_status, doc_type, original_filename FROM documents ORDER BY created_at"))
        for r in result.fetchall():
            print(f"  {r[0]} | {r[1]:10s} | {r[2]:10s} | {r[3]}")
        
        print("\n=== Raw Parses ===")
        result2 = await db.execute(text("SELECT id, document_id, parser_used, parse_confidence FROM raw_parses ORDER BY created_at"))
        for r in result2.fetchall():
            print(f"  {r[0]} | doc={r[1]} | parser={r[2]} | conf={r[3]}")
        
        print("\n=== Invoices ===")
        result3 = await db.execute(text("SELECT count(*) FROM invoices"))
        print(f"  Count: {result3.scalar()}")
        
        print("\n=== Invoice Line Items ===")
        result4 = await db.execute(text("SELECT count(*) FROM invoice_line_items"))
        print(f"  Count: {result4.scalar()}")
        
        print("\n=== Vendors ===")
        result5 = await db.execute(text("SELECT count(*) FROM vendors"))
        print(f"  Count: {result5.scalar()}")

asyncio.run(check())
