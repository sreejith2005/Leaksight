"""Check normalize task and contract parse failure."""
import asyncio, sys
sys.path.insert(0, '.')
from backend.app.core.database import async_session_factory
from sqlalchemy import text

async def check():
    async with async_session_factory() as db:
        # Check raw_parses failure_flags for the contract
        r = await db.execute(text(
            "SELECT rp.id, rp.document_id, rp.failure_flags "
            "FROM raw_parses rp "
            "JOIN documents d ON d.id = rp.document_id "
            "WHERE d.doc_type = 'CONTRACT'"
        ))
        row = r.fetchone()
        if row:
            print(f"Contract raw_parse: {row[0]}")
            print(f"  failure_flags: {row[2]}")
        else:
            print("No raw_parse for contract (parse failed before storage)")
        
        # Check invoice raw_parse
        r2 = await db.execute(text(
            "SELECT rp.id, rp.document_id, rp.failure_flags "
            "FROM raw_parses rp "
            "JOIN documents d ON d.id = rp.document_id "
            "WHERE d.doc_type = 'INVOICE'"
        ))
        row2 = r2.fetchone()
        if row2:
            print(f"\nInvoice raw_parse: {row2[0]}")
            print(f"  failure_flags: {row2[2]}")
        
        # Check if normalization has been done
        r3 = await db.execute(text("SELECT count(*) FROM invoices"))
        r4 = await db.execute(text("SELECT count(*) FROM invoice_line_items"))
        r5 = await db.execute(text("SELECT count(*) FROM vendors"))
        print(f"\nInvoices: {r3.scalar()}, Line Items: {r4.scalar()}, Vendors: {r5.scalar()}")

asyncio.run(check())
