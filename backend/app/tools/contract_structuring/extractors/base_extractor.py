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
    source_name: Optional[str] = None
    source_row_count: int = 0
    failure_flags: List[str] = field(default_factory=list)


@dataclass
class NormalizedLineItem:
    """Output of table_normalizer - one per pricing row."""
    item_description: Optional[str]
    unit_raw: Optional[str]
    unit_price: Optional[float]
    source_column: Optional[str] = None
    contract_id: Optional[str] = None
    currency: Optional[str] = None
    quantity: Optional[float] = None
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
    failure_flags: List[str] = field(default_factory=list)
    row_confidence: float = 0.0

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class ExtractedClauseResult:
    """Output of clause_extractor - one per detected clause."""
    clause_type: str
    raw_text: str
    extracted_value: Optional[str]
    source_page: int
    confidence: float
    needs_review: bool = False


@dataclass
class DocumentExtractionResult:
    """Full extraction output for one document."""

    tables: List[RawTableResult] = field(default_factory=list)
    line_items: List[NormalizedLineItem] = field(default_factory=list)
    clauses: List[Any] = field(default_factory=list)
    confidence: float = 0.0
    failure_flags: List[str] = field(default_factory=list)
    text: str = ""

    @property
    def raw_tables(self) -> List[RawTableResult]:
        return self.tables

    @property
    def parse_confidence(self) -> float:
        return self.confidence
