import asyncio
import sys
sys.path.insert(0, '.')

from backend.app.core.database import async_session_factory
from sqlalchemy import text

async def cleanup():
    async with async_session_factory() as db:
        r1 = await db.execute(text("UPDATE documents SET parse_status='PENDING', low_confidence_flag=false, run_id=NULL WHERE parse_status IN ('PARSING','FAILED')"))
        print(f'Reset {r1.rowcount} documents to PENDING')
        
        # Unlink all documents from analysis runs first
        r1b = await db.execute(text("UPDATE documents SET run_id=NULL WHERE run_id IS NOT NULL"))
        print(f'Unlinked {r1b.rowcount} documents from analysis runs')
        
        r2 = await db.execute(text("DELETE FROM analysis_runs"))
        print(f'Deleted {r2.rowcount} analysis runs')
        
        r3 = await db.execute(text("DELETE FROM raw_parses"))
        print(f'Deleted {r3.rowcount} raw parses')
        
        await db.commit()
        print('Cleanup done')

asyncio.run(cleanup())
