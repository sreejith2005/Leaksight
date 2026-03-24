"""
Contract structuring extraction orchestrator.
Entry point: structure_contract(document_path, tenant_id, db_session)
"""
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def structure_contract(
    document_path: str,
    tenant_id: str = None,
    db_session=None,
) -> Tuple[List, List, int, str]:
    """
    Main entry point for Tool A extraction.

    Args:
        document_path: absolute path to the document file
        tenant_id: tenant UUID string (used for version detection)
        db_session: SQLAlchemy session (used for version detection, optional)

    Returns:
        (line_items, clauses, version_number, base_contract_id)
        line_items: List[NormalizedLineItem]
        clauses: List[ExtractedClauseResult]
        version_number: int (1 if new contract)
        base_contract_id: str or None
    """
    from backend.app.tools.contract_structuring.extractors.multi_page_stitcher import stitch_tables
    from backend.app.tools.contract_structuring.extractors.table_normalizer import normalize_tables
    from backend.app.tools.contract_structuring.extractors.clause_extractor import extract_clauses
    from backend.app.tools.contract_structuring.extractors.version_detector import detect_version

    path = Path(document_path)
    suffix = path.suffix.lower()

    raw_tables = []
    full_text = ""

    if suffix == '.pdf':
        from backend.app.tools.contract_structuring.extractors.pdf_extractor import (
            extract_tables_from_pdf, extract_text_from_pdf
        )
        raw_tables = extract_tables_from_pdf(document_path)
        full_text = extract_text_from_pdf(document_path)

    elif suffix == '.docx':
        from backend.app.tools.contract_structuring.extractors.docx_extractor import (
            extract_tables_from_docx, extract_text_from_docx
        )
        raw_tables = extract_tables_from_docx(document_path)
        full_text = extract_text_from_docx(document_path)

    elif suffix in ('.xlsx', '.xls', '.csv'):
        from backend.app.tools.contract_structuring.extractors.excel_extractor import (
            extract_tables_from_excel
        )
        raw_tables = extract_tables_from_excel(document_path)
        full_text = ""

    else:
        logger.warning(f"Unsupported file type: {suffix}")
        return [], [], 1, None

    logger.info(f"Extracted {len(raw_tables)} raw tables, {len(full_text)} chars of text from {path.name}")

    stitched_tables = stitch_tables(raw_tables)
    line_items = normalize_tables(stitched_tables)
    clauses = extract_clauses(full_text, document_path)

    version_number = 1
    base_contract_id = None
    if tenant_id and db_session:
        version_number, base_contract_id, _ = detect_version(clauses, tenant_id, db_session)

    logger.info(
        f"Extraction complete: {len(line_items)} line items, "
        f"{len(clauses)} clauses, version {version_number}"
    )

    return line_items, clauses, version_number, base_contract_id
