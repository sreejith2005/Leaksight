"""
Column role mapping and line item normalization.

Roles: ITEM_DESCRIPTION, UNIT, UNIT_PRICE, CURRENCY,
       QUANTITY, SLAB_MIN, SLAB_MAX, NOTES, UNKNOWN

Rules (applied in priority order):
  1. Exact keyword match in column header
  2. Fuzzy keyword match using RapidFuzz score >= 80
  3. Value pattern analysis (numeric columns, unit abbreviations)
  4. Unclassified -> UNKNOWN + needs_review = True

Only create a NormalizedLineItem if ITEM_DESCRIPTION + UNIT_PRICE
are both classified. All other fields are nullable.
"""
import logging
import re
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

STRONG_ROLE_SOURCES = {'exact_keyword', 'header_override_exact'}

KNOWN_UNITS = {'mt', 'kg', 'g', 'l', 'ml', 'nos', 'box', 'set', 'sqft', 'sqm', 'rmt',
               'pcs', 'pc', 'each', 'ea', 'ltr', 'litre', 'meter', 'm', 'unit', 'bag'}

ROLE_KEYWORDS = {
    'ITEM_DESCRIPTION': ['item', 'description', 'particulars', 'material', 'product', 'name', 'goods', 'service'],
    'CONTRACT_ID': [
        'contract_id', 'contract id', 'contract_no', 'contract no',
        'contract number', 'ctr_id', 'agreement_id', 'agreement id',
        'contract ref', 'contract_ref', 'po number', 'reference'
    ],
    'UNIT': ['unit', 'uom', 'u/m', 'unit of measure', 'measure', 'uoi'],
    'UNIT_PRICE': ['rate', 'price', 'unit price', 'unit rate', 'amount', 'cost', 'tariff'],
    'CURRENCY': ['currency', 'curr', 'ccy'],
    'QUANTITY': ['qty', 'quantity', 'no.', 'nos', 'count'],
    'SLAB_MIN': ['min qty', 'from', 'min', 'lower'],
    'SLAB_MAX': ['max qty', 'to', 'max', 'upper'],
    'NOTES': ['remarks', 'notes', 'note', 'comment', 'specification'],
}

HEADER_INTENT_RULES = [
    ('UNIT_PRICE', [r'\bunit\s*price\b', r'\bunit\s*rate\b', r'\bprice\b', r'\brate\b', r'\bcost\b', r'\bamount\b', r'\btariff\b']),
    ('UNIT', [r'\buom\b', r'\bunit\b', r'\bmeasure\b']),
    ('CURRENCY', [r'\bcurrency\b', r'\bcurr\b', r'\bccy\b']),
    ('QUANTITY', [r'\bqty\b', r'\bquantity\b', r'\bcount\b', r'\bnos?\b']),
    ('ITEM_DESCRIPTION', [r'\bitem\b', r'\bdescription\b', r'\bmaterial\b', r'\bproduct\b', r'\bparticulars\b']),
]


def _normalize_header(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (value or '').strip().lower()).strip()


def _header_role_override(column_name: str) -> Optional[str]:
    normalized = _normalize_header(column_name)
    if not normalized:
        return None

    if normalized == 'contract id':
        return 'CONTRACT_ID'
    if re.search(r'\bversion\b|\bver\b', normalized):
        return 'UNKNOWN'
    if re.search(r'\b(date|effective|expiry|start|end|valid)\b', normalized):
        return 'UNKNOWN'
    if re.search(
        r'\bcontract\b',
        normalized,
    ) and re.search(
        r'\b(id|no|ref|number)\b',
        normalized,
    ):
        return 'CONTRACT_ID'
    if re.search(r'\b(vendor|supplier|contract)\b', normalized):
        return 'UNKNOWN'

    for role, patterns in HEADER_INTENT_RULES:
        if any(re.search(pattern, normalized) for pattern in patterns):
            if role == 'UNIT' and re.search(r'\b(price|rate|cost|amount|tariff)\b', normalized):
                return 'UNIT_PRICE'
            return role

    return None


def normalize_tables(raw_tables: List, stitched: bool = True) -> List:
    """
    Given a list of RawTableResult (already stitched), produce NormalizedLineItem list.
    Skips continuation tables if stitched=True (their rows are accessed via get_merged_rows).
    """
    from backend.app.tools.contract_structuring.extractors.base_extractor import NormalizedLineItem
    from backend.app.tools.contract_structuring.extractors.multi_page_stitcher import get_merged_rows

    results = []

    for idx, table in enumerate(raw_tables):
        if stitched and table.is_continuation:
            continue

        rows = get_merged_rows(raw_tables, idx) if stitched else table.raw_table_json
        if not rows:
            continue

        column_roles = _map_column_roles(list(rows[0].keys()), rows)

        if 'ITEM_DESCRIPTION' not in column_roles.values() or 'UNIT_PRICE' not in column_roles.values():
            logger.debug(f"Table on page {table.source_page}: missing ITEM_DESCRIPTION or UNIT_PRICE - skipping")
            continue

        for row in rows:
            item = _extract_line_item(row, column_roles, table.source_page, table.extraction_method)
            if item is not None:
                results.append(item)

    return results


def _map_column_roles(column_names: List[str], sample_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, str]:
    """Map each column name to a role. Returns {column_name: role}."""
    role_sources: Dict[str, str] = {}
    return _map_column_roles_with_sources(column_names, sample_rows, role_sources)


def _map_column_roles_with_sources(
    column_names: List[str],
    sample_rows: Optional[List[Dict[str, Any]]] = None,
    role_sources: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Map each column name to a role and optionally track assignment source."""
    from rapidfuzz import fuzz

    roles = {}
    sources = role_sources if role_sources is not None else {}
    for col in column_names:
        override_role = _header_role_override(col)
        if override_role is not None:
            roles[col] = override_role
            normalized_col = col.strip().lower()
            if normalized_col in ROLE_KEYWORDS.get(override_role, []):
                sources[col] = 'header_override_exact'
            else:
                sources[col] = 'header_override_pattern'
            continue

        col_lower = col.strip().lower()
        role = None

        for role_name, keywords in ROLE_KEYWORDS.items():
            if col_lower in keywords:
                role = role_name
                sources[col] = 'exact_keyword'
                break

        if not role:
            best_score = 0
            best_role = None
            for role_name, keywords in ROLE_KEYWORDS.items():
                if role_name == 'CONTRACT_ID' and not _is_contract_id_header_candidate(col_lower):
                    continue
                for kw in keywords:
                    score = fuzz.partial_ratio(col_lower, kw)
                    if score > best_score:
                        best_score = score
                        best_role = role_name
            if best_score >= 80:
                role = best_role
                sources[col] = 'fuzzy_keyword'

        roles[col] = role or 'UNKNOWN'
        if col not in sources:
            sources[col] = 'default_unknown'

    if sample_rows:
        roles = _refine_roles_by_values(roles, sample_rows, sources)

    roles = _apply_unit_numeric_guard(roles, sample_rows or [], sources)
    roles = _apply_contract_id_guard(roles, sample_rows or [], sources)

    return roles


def _is_contract_id_header_candidate(header: str) -> bool:
    normalized = _normalize_header(header)
    if not normalized:
        return False
    if normalized == 'contract id':
        return True
    if re.search(r'\bversion\b|\bver\b', normalized):
        return False
    return bool(re.search(r'\bcontract\b', normalized) and re.search(r'\b(id|no|ref|number)\b', normalized))


def _sample_non_empty_values(sample_rows: List[Dict[str, Any]], column_name: str, limit: int = 10) -> List[str]:
    values: List[str] = []
    for row in sample_rows:
        value = str(row.get(column_name, '')).strip()
        if not value:
            continue
        values.append(value)
        if len(values) >= limit:
            break
    return values


def _is_plain_integer_string(value: str) -> bool:
    return bool(re.fullmatch(r'\d+', (value or '').strip()))


def _looks_like_small_integer_series(values: List[str]) -> bool:
    if not values:
        return False
    if not all(_is_plain_integer_string(value) for value in values):
        return False
    return all(int(value) <= 1000 for value in values)


def _looks_like_textual_contract_id(values: List[str]) -> bool:
    if not values:
        return False
    return any(re.search(r'[A-Za-z]', value) or re.search(r'[-_/]', value) for value in values)


def _is_date_like(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False

    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text):
        return True
    if re.search(r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b", text):
        return True
    if re.search(r"\b\d{1,2}\s+[a-z]{3,9}\s+\d{2,4}\b", text):
        return True
    if re.search(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
        text,
    ) and re.search(r"\b\d{2,4}\b", text):
        return True

    return False


def _refine_roles_by_values(
    roles: Dict[str, str],
    sample_rows: List[Dict[str, Any]],
    role_sources: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    sample = sample_rows[: min(len(sample_rows), 5)]
    if not sample:
        return roles

    sources = role_sources if role_sources is not None else {}

    unit_cols = [c for c, r in roles.items() if r == 'UNIT']
    price_cols = [c for c, r in roles.items() if r == 'UNIT_PRICE']

    if not unit_cols or not price_cols:
        return roles

    def _unit_like_score(col: str) -> int:
        score = 0
        for row in sample:
            value = str(row.get(col, '')).strip().lower()
            if not value:
                continue
            if value in KNOWN_UNITS:
                score += 3
            elif re.fullmatch(r"[a-z]{1,6}", value):
                score += 1
            if _parse_numeric(value)[0] is not None:
                score -= 2
        return score

    def _price_like_score(col: str) -> int:
        score = 0
        for row in sample:
            value = str(row.get(col, '')).strip()
            if not value:
                continue
            parsed, _ = _parse_numeric(value)
            if parsed is not None:
                score += 2
            if _is_date_like(value):
                score -= 3
        return score

    best_unit = max(unit_cols, key=_unit_like_score)
    best_price = max(price_cols, key=_price_like_score)

    if best_unit != best_price:
        for col in unit_cols:
            roles[col] = 'UNKNOWN'
            if sources.get(col) not in STRONG_ROLE_SOURCES:
                sources[col] = 'value_refine_demoted'
        for col in price_cols:
            roles[col] = 'UNKNOWN'
            if sources.get(col) not in STRONG_ROLE_SOURCES:
                sources[col] = 'value_refine_demoted'
        roles[best_unit] = 'UNIT'
        if sources.get(best_unit) not in STRONG_ROLE_SOURCES:
            sources[best_unit] = 'value_refine_unit'
        roles[best_price] = 'UNIT_PRICE'
        if sources.get(best_price) not in STRONG_ROLE_SOURCES:
            sources[best_price] = 'value_refine_price'

    return roles


def _apply_unit_numeric_guard(
    roles: Dict[str, str],
    sample_rows: List[Dict[str, Any]],
    role_sources: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    if not sample_rows:
        return roles

    sources = role_sources if role_sources is not None else {}
    numeric_pattern = re.compile(r'^[\d,.]+$')

    for col, role in list(roles.items()):
        if role != 'UNIT':
            continue

        # Preserve explicit UNIT intent from header keywords.
        if sources.get(col) in STRONG_ROLE_SOURCES:
            continue

        non_empty_values: List[str] = []
        for row in sample_rows:
            value = str(row.get(col, '')).strip()
            if not value:
                continue
            non_empty_values.append(value)
            if len(non_empty_values) >= 10:
                break

        if not non_empty_values:
            continue

        purely_numeric_count = sum(1 for value in non_empty_values if numeric_pattern.match(value))
        if (purely_numeric_count / len(non_empty_values)) > 0.5:
            roles[col] = 'UNKNOWN'
            sources[col] = 'numeric_guard_demoted'

    return roles


def _apply_contract_id_guard(
    roles: Dict[str, str],
    sample_rows: List[Dict[str, Any]],
    role_sources: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    contract_cols = [col for col, role in roles.items() if role == 'CONTRACT_ID']
    if not contract_cols:
        return roles

    sources = role_sources if role_sources is not None else {}
    scores: Dict[str, int] = {}

    for col in contract_cols:
        normalized = _normalize_header(col)
        values = _sample_non_empty_values(sample_rows, col)

        if re.search(r'\bversion\b|\bver\b', normalized):
            roles[col] = 'UNKNOWN'
            sources[col] = 'contract_id_guard_version_header'
            continue

        if values and not _looks_like_textual_contract_id(values):
            if _looks_like_small_integer_series(values) or all(_is_plain_integer_string(value) for value in values):
                roles[col] = 'UNKNOWN'
                sources[col] = 'contract_id_guard_integer_values'
                continue

        score = 0
        if normalized == 'contract id':
            score += 10
        if re.search(r'\bcontract\b', normalized):
            score += 4
        if re.search(r'\b(id|no|ref|number)\b', normalized):
            score += 3
        if _looks_like_textual_contract_id(values):
            score += 5
        if values and all(_is_plain_integer_string(value) for value in values):
            score -= 10
        scores[col] = score

    surviving_cols = [col for col, role in roles.items() if role == 'CONTRACT_ID']
    if len(surviving_cols) <= 1:
        return roles

    best_col = max(surviving_cols, key=lambda col: scores.get(col, 0))
    for col in surviving_cols:
        if col == best_col:
            continue
        roles[col] = 'UNKNOWN'
        sources[col] = 'contract_id_guard_deduped'

    return roles


def _extract_line_item(row: Dict, column_roles: Dict[str, str], source_page: int, method: str):
    from backend.app.tools.contract_structuring.extractors.base_extractor import NormalizedLineItem

    item_desc = None
    item_conf = 0.0
    contract_id_val = None
    unit_raw = None
    unit_conf = 0.0
    unit_price = None
    price_conf = 0.0
    currency = "INR"

    for col, role in column_roles.items():
        value = str(row.get(col, '')).strip()
        if not value:
            continue

        if role == 'ITEM_DESCRIPTION':
            item_desc = value
            item_conf = 0.9 if len(value) > 3 else 0.5

        elif role == 'CONTRACT_ID':
            contract_id_val = value

        elif role == 'UNIT':
            unit_raw = value
            unit_conf = 1.0 if value.lower() in KNOWN_UNITS else 0.7

        elif role == 'UNIT_PRICE':
            parsed, conf = _parse_numeric(value)
            if parsed is not None:
                unit_price = parsed
                price_conf = conf

        elif role == 'CURRENCY':
            currency = value.upper() if len(value) <= 5 else "INR"

    if not item_desc and unit_price is None:
        return None

    needs_review = (
        item_conf < 0.6 or
        price_conf < 0.6 or
        unit_conf < 0.6 or
        item_desc is None or
        unit_price is None
    )

    return NormalizedLineItem(
        item_description=item_desc,
        unit_raw=unit_raw,
        unit_price=unit_price,
        contract_id=contract_id_val,
        currency=currency,
        source_page=source_page,
        item_confidence=item_conf,
        price_confidence=price_conf,
        unit_confidence=unit_conf,
        needs_review=needs_review,
        extraction_method=method,
    )


def _parse_numeric(value: str):
    """Parse a string as a positive number. Returns (float, confidence) or (None, 0.0)."""
    if _is_date_like(value):
        return None, 0.0

    match = re.search(r'(\d[\d,]*(?:\.\d+)?)', value or '')
    if not match:
        return None, 0.0
    cleaned = match.group(1).replace(',', '')
    try:
        result = float(cleaned)
        if result <= 0:
            return None, 0.0
        return result, 0.95
    except ValueError:
        return None, 0.0


class TableNormalizer:
    """Backward-compatible class API for existing task flow."""

    def classify_columns(self, rows: List[Dict]) -> Dict[str, str]:
        if not rows:
            return {}
        return _map_column_roles(list(rows[0].keys()), rows)

    def detect_column_roles(self, table_like) -> Dict[str, str]:
        if table_like is None:
            return {}
        if hasattr(table_like, 'to_dict'):
            rows = table_like.to_dict('records')
        else:
            rows = table_like
        if not rows:
            return {}
        return self.classify_columns(rows)

    def normalize_table(self, stitched_table) -> List:
        from backend.app.tools.contract_structuring.extractors.base_extractor import NormalizedLineItem

        rows = getattr(stitched_table, "merged_rows", [])
        source_page = getattr(stitched_table, "source_page", 0) or 0
        if not rows:
            return []

        column_roles = _map_column_roles(list(rows[0].keys()), rows)
        if 'ITEM_DESCRIPTION' not in column_roles.values() or 'UNIT_PRICE' not in column_roles.values():
            return []

        results = []
        for row in rows:
            item = _extract_line_item(row, column_roles, source_page, "")
            if item is not None:
                results.append(item)
        return results
