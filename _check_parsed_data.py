"""Check what the Excel parser extracted."""
import asyncio, sys, json
sys.path.insert(0, '.')
from backend.app.core.database import async_session_factory
from sqlalchemy import text

async def check():
    async with async_session_factory() as db:
        r = await db.execute(text(
            "SELECT structured_output_jsonb->'header' as header, "
            "jsonb_array_length(structured_output_jsonb->'line_items') as li_count "
            "FROM raw_parses WHERE id = '08034217-2913-48a2-bb59-50a5e1cf6ebb'"
        ))
        row = r.fetchone()
        if row:
            print(f"Header: {json.dumps(row[0], indent=2)}")
            print(f"Line items count: {row[1]}")
        
        # Also check first few line items to see data structure
        r2 = await db.execute(text(
            "SELECT structured_output_jsonb->'line_items'->0 as first_item "
            "FROM raw_parses WHERE id = '08034217-2913-48a2-bb59-50a5e1cf6ebb'"
        ))
        row2 = r2.fetchone()
        if row2:
            print(f"\nFirst line item: {json.dumps(row2[0], indent=2)}")
        
        # Check raw_extracted_data for column mapping
        r3 = await db.execute(text(
            "SELECT structured_output_jsonb->'raw_extracted_data'->'column_mapping' as cols "
            "FROM raw_parses WHERE id = '08034217-2913-48a2-bb59-50a5e1cf6ebb'"
        ))
        row3 = r3.fetchone()
        if row3:
            print(f"\nColumn mapping: {json.dumps(row3[0], indent=2)}")

asyncio.run(check())
