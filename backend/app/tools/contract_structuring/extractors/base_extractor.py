from dataclasses import dataclass, field
from typing import Optional, List, Any, Dict


@dataclass
class RawTableResult:
    """Output of a single table extraction attempt from any source."""
    source_page: int
    extraction_method: str
    raw_table_json: List[Dict[str, Any]]
    table_confidence: float
    column_count: int
    row_count: int
    is_continuation: bool = False
    continued_from_index: Optional[int] = None


@dataclass
class NormalizedLineItem:
    """Output of table_normalizer - one per pricing row."""
    item_description: Optional[str]
    unit_raw: Optional[str]
    unit_price: Optional[float]
    contract_id: Optional[str] = None
    currency: str = "INR"
    slab_info: Optional[List[Dict]] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    version_number: int = 1
    source_page: int = 0
    item_confidence: float = 0.0
    price_confidence: float = 0.0
    unit_confidence: float = 0.0
    needs_review: bool = False
    extraction_method: str = ""


@dataclass
class ExtractedClauseResult:
    """Output of clause_extractor - one per detected clause."""
    clause_type: str
    raw_text: str
    extracted_value: Optional[str]
    source_page: int
    confidence: float
    needs_review: bool = False
