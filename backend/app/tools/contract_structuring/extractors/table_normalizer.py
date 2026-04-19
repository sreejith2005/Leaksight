"""
Format-agnostic table normalization for Tool A.

This module converts raw extractor output into normalized pricing rows without
rejecting tables purely because they do not match a single demo schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

from backend.app.tools.contract_structuring.extractors.base_extractor import (
    NormalizedLineItem,
    RawTableResult,
)

LINE_ITEM_PATTERN = re.compile(
    r"(?P<item>[A-Za-z][^\n]{2,120}?)\s+"
    r"(?P<quantity>\d+(?:\.\d+)?)\s+"
    r"(?P<unit>[A-Za-z]{1,16})\s+"
    r"(?P<price>(?:USD|INR|EUR|GBP|AED|SGD|AUD|CAD|JPY|CNY|CHF|Rs\.?|₹|€|£|\$)\s*[\d,]+(?:\.\d{1,4})?|[\d,]+(?:\.\d{1,4})?)",
    re.IGNORECASE,
)

KNOWN_UNITS = {
    "bag",
    "box",
    "count",
    "day",
    "days",
    "ea",
    "each",
    "g",
    "hr",
    "hrs",
    "hour",
    "kg",
    "l",
    "liter",
    "litre",
    "ltr",
    "m",
    "measure",
    "meter",
    "ml",
    "mt",
    "no",
    "nos",
    "pc",
    "pcs",
    "piece",
    "pieces",
    "rmt",
    "set",
    "sqm",
    "sqft",
    "unit",
    "uom",
}

ROLE_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "ITEM_DESCRIPTION",
        [
            "item",
            "description",
            "desc",
            "product",
            "service",
            "material",
            "particulars",
            "details",
            "name",
            "goods",
            "work",
            "activity",
            "scope",
            "deliverable",
            "component",
            "part",
        ],
    ),
    (
        "UNIT_PRICE",
        [
            "unit price",
            "unit rate",
            "rate",
            "price",
            "cost",
            "amount",
            "value",
            "charge",
            "fee",
            "tariff",
            "unit cost",
            "per unit",
            "each",
        ],
    ),
    (
        "QUANTITY",
        [
            "qty",
            "quantity",
            "units",
            "nos",
            "count",
            "volume",
            "number",
            "pieces",
            "pcs",
            "no.",
            "no of units",
        ],
    ),
    (
        "UNIT",
        [
            "unit",
            "uom",
            "measure",
            "measurement",
            "each",
            "per",
        ],
    ),
    (
        "CURRENCY",
        [
            "currency",
            "curr",
            "ccy",
            "denomination",
        ],
    ),
]

CONTRACT_ID_KEYWORDS = [
    "agreement id",
    "agreement ref",
    "contract id",
    "contract no",
    "contract number",
    "contract ref",
    "contract reference",
    "contract_id",
    "reference",
]

GENERIC_HEADER_RE = re.compile(r"^(?:\d+|col(?:umn)?[_\s-]*\d+)$", re.IGNORECASE)
SUBTOTAL_RE = re.compile(r"\b(total|subtotal|grand total|net total|amount payable)\b", re.IGNORECASE)

CURRENCY_DEFINITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "INR": {
        "headers": ("inr", "rs", "rs.", "rupee", "rupees", "indian rupee", "indian rupees", "₹"),
        "cells": ("₹", "rs", "rs.", "inr", "rupee", "rupees", "indian rupee", "indian rupees"),
        "document": ("₹", "rs", "rs.", "inr", "rupee", "rupees", "indian rupee", "indian rupees"),
    },
    "USD": {
        "headers": ("usd", "us$", "us dollar", "us dollars", "dollar", "dollars", "$"),
        "cells": ("usd", "us$", "us dollar", "us dollars", "$"),
        "document": ("usd", "us$", "us dollar", "us dollars", "$"),
    },
    "EUR": {
        "headers": ("eur", "euro", "euros", "€"),
        "cells": ("eur", "euro", "euros", "€"),
        "document": ("eur", "euro", "euros", "€"),
    },
    "GBP": {
        "headers": ("gbp", "pound", "pounds", "sterling", "£"),
        "cells": ("gbp", "pound", "pounds", "sterling", "£"),
        "document": ("gbp", "pound", "pounds", "sterling", "£"),
    },
    "AED": {
        "headers": ("aed", "uae dirham", "dirham", "dirhams", "د.إ"),
        "cells": ("aed", "uae dirham", "dirham", "dirhams", "د.إ"),
        "document": ("aed", "uae dirham", "dirham", "dirhams", "د.إ"),
    },
    "SGD": {
        "headers": ("sgd", "s$", "singapore dollar", "singapore dollars"),
        "cells": ("sgd", "s$", "singapore dollar", "singapore dollars"),
        "document": ("sgd", "s$", "singapore dollar", "singapore dollars"),
    },
    "AUD": {
        "headers": ("aud", "a$", "au$", "australian dollar", "australian dollars"),
        "cells": ("aud", "a$", "au$", "australian dollar", "australian dollars"),
        "document": ("aud", "a$", "au$", "australian dollar", "australian dollars"),
    },
    "CAD": {
        "headers": ("cad", "c$", "canadian dollar", "canadian dollars"),
        "cells": ("cad", "c$", "canadian dollar", "canadian dollars"),
        "document": ("cad", "c$", "canadian dollar", "canadian dollars"),
    },
    "JPY": {
        "headers": ("jpy", "japanese yen", "yen", "jp¥", "¥"),
        "cells": ("jpy", "japanese yen", "yen", "jp¥", "¥"),
        "document": ("jpy", "japanese yen", "yen", "jp¥", "¥"),
    },
    "CNY": {
        "headers": ("cny", "rmb", "renminbi", "yuan", "cn¥", "￥", "元"),
        "cells": ("cny", "rmb", "renminbi", "yuan", "cn¥", "￥", "元"),
        "document": ("cny", "rmb", "renminbi", "yuan", "cn¥", "￥", "元"),
    },
    "CHF": {
        "headers": ("chf", "swiss franc", "swiss francs", "fr"),
        "cells": ("chf", "swiss franc", "swiss francs", "fr"),
        "document": ("chf", "swiss franc", "swiss francs", "fr"),
    },
}

_CURRENCY_PATTERN_ORDER = ["AED", "SGD", "AUD", "CAD", "USD", "EUR", "GBP", "INR", "JPY", "CNY", "CHF"]
_CURRENCY_SPECIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AED", re.compile(r"(?:^|[\s(])(?:aed|uae\s+dirham|dirham|dirhams|د\.إ)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("SGD", re.compile(r"(?:^|[\s(])(?:sgd|s\$|singapore\s+dollars?)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("AUD", re.compile(r"(?:^|[\s(])(?:aud|a\$|au\$|australian\s+dollars?)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("CAD", re.compile(r"(?:^|[\s(])(?:cad|c\$|canadian\s+dollars?)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("USD", re.compile(r"(?:^|[\s(])(?:usd|us\$|us\s+dollars?|dollars?|\$)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("EUR", re.compile(r"(?:^|[\s(])(?:eur|euros?|€)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("GBP", re.compile(r"(?:^|[\s(])(?:gbp|pounds?|sterling|£)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("INR", re.compile(r"(?:^|[\s(])(?:inr|rs\.?|rupees?|indian\s+rupees?|₹)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("JPY", re.compile(r"(?:^|[\s(])(?:jpy|japanese\s+yen|yen|jp¥|¥)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("CNY", re.compile(r"(?:^|[\s(])(?:cny|rmb|renminbi|yuan|cn¥|￥|元)(?:[\s):,-]|$)", re.IGNORECASE)),
    ("CHF", re.compile(r"(?:^|[\s(])(?:chf|swiss\s+francs?|fr)(?:[\s):,-]|$)", re.IGNORECASE)),
]


@dataclass
class NormalizationSummary:
    line_items: list[NormalizedLineItem] = field(default_factory=list)
    failure_flags: list[str] = field(default_factory=list)
    confidence: float = 0.10
    retained_rows: int = 0
    source_rows: int = 0
    quantity_detected: bool = False
    document_currency_hint: str | None = None

    @property
    def row_retention(self) -> float:
        if self.source_rows <= 0:
            return 1.0 if self.retained_rows > 0 else 0.0
        return self.retained_rows / self.source_rows


@dataclass
class _TableLayout:
    item_column: str | None
    price_columns: list[str]
    quantity_column: str | None
    unit_column: str | None
    currency_column: str | None
    contract_id_column: str | None
    item_inferred: bool = False
    price_inferred: bool = False


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(value).lower()).strip()


def _contains_keyword(haystack: str, needle: str) -> bool:
    normalized_haystack = _normalize_header(haystack)
    normalized_needle = _normalize_header(needle)
    if not normalized_haystack or not normalized_needle:
        return False
    if len(normalized_needle) <= 3:
        return bool(re.search(rf"\b{re.escape(normalized_needle)}\b", normalized_haystack))
    return normalized_needle in normalized_haystack


def _is_generic_header(value: str) -> bool:
    normalized = _normalize_header(value)
    return not normalized or bool(GENERIC_HEADER_RE.fullmatch(normalized))


def _sanitize_headers(headers: Iterable[str]) -> list[str]:
    cleaned_headers: list[str] = []
    seen: dict[str, int] = {}
    for idx, raw_value in enumerate(headers, start=1):
        cleaned = _clean_text(raw_value) or f"column_{idx}"
        seen[cleaned] = seen.get(cleaned, 0) + 1
        if seen[cleaned] > 1:
            cleaned = f"{cleaned}_{seen[cleaned]}"
        cleaned_headers.append(cleaned)
    return cleaned_headers


def _is_date_like(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in (
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
            r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b",
        )
    )


def _parse_numeric(value: str) -> tuple[float | None, float]:
    text = _clean_text(value)
    if not text or _is_date_like(text):
        return None, 0.0

    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", text)
    if not match:
        return None, 0.0

    try:
        numeric = float(match.group(1).replace(",", ""))
    except ValueError:
        return None, 0.0

    if numeric <= 0:
        return None, 0.0

    confidence = 0.95
    if _find_currency_code(text, kind="cells"):
        confidence = 0.97
    return numeric, confidence


def _find_currency_code(value: str | None, *, kind: str) -> str | None:
    text = _clean_text(value)
    if not text:
        return None

    for code, pattern in _CURRENCY_SPECIAL_PATTERNS:
        if pattern.search(text):
            if code == "JPY" and "cn¥" in text.lower():
                continue
            return code

    normalized = _normalize_header(text)
    for code in _CURRENCY_PATTERN_ORDER:
        for token in CURRENCY_DEFINITIONS[code][kind]:
            token_normalized = _normalize_header(token)
            if token_normalized and _contains_keyword(normalized, token_normalized):
                return code
            if token and not token.isalpha() and token in text:
                return code
    return None


def extract_currency_from_header(column_header: str) -> str | None:
    return _find_currency_code(column_header, kind="headers")


def extract_currency_from_cell(cell_value: str) -> tuple[float | None, str | None]:
    cell_str = _clean_text(cell_value)
    if not cell_str:
        return None, None
    numeric, _ = _parse_numeric(cell_str)
    if numeric is None:
        return None, None
    return numeric, _find_currency_code(cell_str, kind="cells")


def resolve_currency(
    cell_value: str,
    column_header: str,
    document_default: str | None,
) -> tuple[float | None, str | None]:
    numeric_value, _ = _parse_numeric(cell_value)
    if numeric_value is None:
        return None, None

    header_currency = extract_currency_from_header(column_header)
    if header_currency:
        return numeric_value, header_currency

    _numeric, cell_currency = extract_currency_from_cell(cell_value)
    if cell_currency:
        return numeric_value, cell_currency

    if document_default:
        return numeric_value, document_default

    return numeric_value, None


def _detect_document_currency_hint(document_text: str | None, rows: list[dict[str, Any]]) -> str | None:
    counts = {code: 0 for code in CURRENCY_DEFINITIONS}
    candidates = [document_text or ""]
    for row in rows:
        candidates.extend(str(key or "") for key in row.keys())
        candidates.extend(str(value or "") for value in row.values())

    for text in candidates:
        cleaned = _clean_text(text)
        if not cleaned:
            continue
        for code in counts:
            if _find_currency_code(cleaned, kind="document") == code:
                counts[code] += 1

    best_code = max(counts, key=counts.get, default=None)
    if best_code and counts[best_code] > 0:
        return best_code
    return None


def _header_to_role(column_name: str) -> str | None:
    normalized = _normalize_header(column_name)
    if not normalized:
        return None

    if re.search(r"\bversion\b|\bver\b", normalized):
        return "UNKNOWN"
    if re.search(r"\b(date|effective|expiry|start|end|valid)\b", normalized):
        return "UNKNOWN"
    if re.search(r"\b(vendor|supplier)\b", normalized):
        return "UNKNOWN"

    if any(_contains_keyword(normalized, keyword) for keyword in CONTRACT_ID_KEYWORDS):
        return "CONTRACT_ID"

    for role, keywords in ROLE_KEYWORDS:
        for keyword in keywords:
            if _contains_keyword(normalized, keyword):
                return role
    return None


def _sample_non_empty_values(sample_rows: list[dict[str, Any]], column_name: str, limit: int = 12) -> list[str]:
    values: list[str] = []
    for row in sample_rows:
        value = _clean_text(row.get(column_name, ""))
        if not value:
            continue
        values.append(value)
        if len(values) >= limit:
            break
    return values


def _is_plain_integer_string(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", _clean_text(value)))


def _looks_like_small_integer_series(values: list[str]) -> bool:
    if not values or not all(_is_plain_integer_string(value) for value in values):
        return False
    return all(int(value) <= 1000 for value in values)


def _looks_like_textual_contract_id(values: list[str]) -> bool:
    if not values:
        return False
    return any(re.search(r"[A-Za-z]|[-_/]", value) for value in values)


def _apply_unit_numeric_guard(roles: Dict[str, str], sample_rows: list[dict[str, Any]]) -> Dict[str, str]:
    exact_unit_headers = {
        "each",
        "measure",
        "measurement",
        "per",
        "unit",
        "uom",
    }
    for column_name, role in list(roles.items()):
        if role != "UNIT":
            continue
        if _normalize_header(column_name) in exact_unit_headers:
            continue
        values = _sample_non_empty_values(sample_rows, column_name)
        if not values:
            continue
        numeric_hits = sum(1 for value in values if re.fullmatch(r"[\d,.]+", value))
        if numeric_hits / len(values) > 0.5:
            roles[column_name] = "UNKNOWN"
    return roles


def _apply_contract_id_guard(roles: Dict[str, str], sample_rows: list[dict[str, Any]]) -> Dict[str, str]:
    contract_columns = [column_name for column_name, role in roles.items() if role == "CONTRACT_ID"]
    if len(contract_columns) <= 1:
        return roles

    scores: dict[str, int] = {}
    for column_name in contract_columns:
        normalized = _normalize_header(column_name)
        values = _sample_non_empty_values(sample_rows, column_name)
        score = 0
        if any(keyword in normalized for keyword in CONTRACT_ID_KEYWORDS):
            score += 5
        if _looks_like_textual_contract_id(values):
            score += 5
        if _looks_like_small_integer_series(values):
            score -= 10
        scores[column_name] = score

    best_column = max(contract_columns, key=lambda column_name: scores.get(column_name, 0))
    for column_name in contract_columns:
        if column_name != best_column:
            roles[column_name] = "UNKNOWN"
    return roles


def _map_column_roles(
    column_names: List[str],
    sample_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    roles = {column_name: (_header_to_role(column_name) or "UNKNOWN") for column_name in column_names}
    sample_rows = sample_rows or []
    if sample_rows:
        roles = _apply_contract_id_guard(roles, sample_rows)
        roles = _apply_unit_numeric_guard(roles, sample_rows)
    return roles


def _row_values_from_table_rows(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    if not rows:
        return [], []
    column_order = list(rows[0].keys())
    values = [[_clean_text(row.get(column_name, "")) for column_name in column_order] for row in rows]
    return column_order, values


def _header_candidate_score(values: list[str]) -> tuple[float, int]:
    non_empty = [value for value in values if value]
    if not non_empty:
        return 0.0, 0

    non_numeric_strings = sum(
        1 for value in non_empty if _parse_numeric(value)[0] is None and re.search(r"[A-Za-z]", value)
    )
    ratio = non_numeric_strings / len(non_empty)
    keyword_hits = sum(
        1
        for value in non_empty
        if _header_to_role(value) not in {None, "UNKNOWN"} or extract_currency_from_header(value)
    )
    return ratio, keyword_hits


def _prepare_table_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[str], int]:
    if not rows:
        return [], [], [], 0

    source_headers, matrix = _row_values_from_table_rows(rows)
    header_row_index = -1
    best_score = (0.0, 0)

    for idx, values in enumerate(matrix[:10]):
        ratio, keyword_hits = _header_candidate_score(values)
        if ratio > 0.5 and (keyword_hits > 0 or all(_is_generic_header(header) for header in source_headers)):
            candidate_score = (ratio, keyword_hits)
            if candidate_score > best_score:
                best_score = candidate_score
                header_row_index = idx

    if header_row_index >= 0 and (header_row_index > 0 or all(_is_generic_header(header) for header in source_headers)):
        headers = _sanitize_headers(matrix[header_row_index])
        data_matrix = matrix[header_row_index + 1 :]
    else:
        headers = _sanitize_headers(source_headers)
        data_matrix = matrix
        header_row_index = -1

    prepared_rows = [
        {
            headers[column_index]: values[column_index] if column_index < len(values) else ""
            for column_index in range(len(headers))
        }
        for values in data_matrix
    ]
    return prepared_rows, headers, source_headers, header_row_index


def _is_blank_row(row: dict[str, Any]) -> bool:
    return not any(_clean_text(value) for value in row.values())


def _is_header_repeat(row: dict[str, Any], headers: list[str]) -> bool:
    values = [_normalize_header(value) for value in row.values() if _clean_text(value)]
    if not values:
        return False
    normalized_headers = {_normalize_header(header) for header in headers if _normalize_header(header)}
    return len(values) == len(normalized_headers.intersection(values))


def _is_subtotal_row(row: dict[str, Any]) -> bool:
    joined = " ".join(_clean_text(value) for value in row.values())
    return bool(SUBTOTAL_RE.search(joined))


def _numeric_columns_by_position(headers: list[str], rows: list[dict[str, Any]]) -> list[str]:
    numeric_columns: list[str] = []
    for header in headers:
        values = [_clean_text(row.get(header, "")) for row in rows if _clean_text(row.get(header, ""))]
        if not values:
            continue
        numeric_hits = sum(1 for value in values if _parse_numeric(value)[0] is not None)
        if numeric_hits / len(values) >= 0.5:
            numeric_columns.append(header)
    return numeric_columns


def _resolve_table_layout(
    headers: list[str],
    prepared_rows: list[dict[str, Any]],
    column_roles: dict[str, str],
) -> _TableLayout:
    item_column = next((column for column, role in column_roles.items() if role == "ITEM_DESCRIPTION"), None)
    price_columns = [column for column, role in column_roles.items() if role == "UNIT_PRICE"]
    quantity_column = next((column for column, role in column_roles.items() if role == "QUANTITY"), None)
    unit_column = next((column for column, role in column_roles.items() if role == "UNIT"), None)
    currency_column = next((column for column, role in column_roles.items() if role == "CURRENCY"), None)
    contract_id_column = next((column for column, role in column_roles.items() if role == "CONTRACT_ID"), None)

    numeric_columns = _numeric_columns_by_position(headers, prepared_rows)
    item_inferred = False
    price_inferred = False

    if item_column is None and headers:
        item_column = headers[0]
        item_inferred = True

    if not price_columns and numeric_columns:
        price_columns = [numeric_columns[-1]]
        price_inferred = True

    if quantity_column is None and len(numeric_columns) >= 2:
        quantity_column = numeric_columns[-2]

    return _TableLayout(
        item_column=item_column,
        price_columns=price_columns,
        quantity_column=quantity_column,
        unit_column=unit_column,
        currency_column=currency_column,
        contract_id_column=contract_id_column,
        item_inferred=item_inferred,
        price_inferred=price_inferred,
    )


def _detect_price_column_conflicts(
    price_columns: list[str],
    rows: list[dict[str, Any]],
) -> set[str]:
    conflicts: set[str] = set()
    for column_name in price_columns:
        header_currency = extract_currency_from_header(column_name)
        currencies: set[str] = set()
        for row in rows:
            value = _clean_text(row.get(column_name, ""))
            if not value:
                continue
            _numeric, currency = extract_currency_from_cell(value)
            if currency:
                currencies.add(currency)

        if header_currency:
            if any(currency != header_currency for currency in currencies):
                conflicts.add(column_name)
            continue

        if len(currencies) > 1:
            conflicts.add(column_name)
    return conflicts


def _compute_row_confidence(
    *,
    item_description: str | None,
    unit_price: float | None,
    currency: str | None,
    quantity: float | None,
    item_inferred: bool,
    price_inferred: bool,
    parse_error: bool,
) -> float:
    confidence = 0.50
    if item_description:
        confidence += 0.20
    if unit_price is not None:
        confidence += 0.15
    if currency:
        confidence += 0.10
    if quantity is not None:
        confidence += 0.05

    if currency is None:
        confidence -= 0.10
    if item_inferred:
        confidence -= 0.15
    if price_inferred:
        confidence -= 0.20
    if parse_error:
        confidence -= 0.10

    return max(0.10, min(0.98, round(confidence, 4)))


def _build_line_item(
    *,
    row: dict[str, Any],
    layout: _TableLayout,
    price_column: str,
    row_currency_hint: str | None,
    document_currency_hint: str | None,
    source_page: int,
    method: str,
    conflict_columns: set[str],
) -> NormalizedLineItem | None:
    item_description = _clean_text(row.get(layout.item_column, "")) if layout.item_column else None
    item_description = item_description or None

    unit_raw = _clean_text(row.get(layout.unit_column, "")) if layout.unit_column else None
    unit_raw = unit_raw or None

    quantity = None
    parse_error = False
    if layout.quantity_column:
        quantity_text = _clean_text(row.get(layout.quantity_column, ""))
        if quantity_text:
            quantity, _ = _parse_numeric(quantity_text)
            if quantity is None:
                parse_error = True

    contract_id = _clean_text(row.get(layout.contract_id_column, "")) if layout.contract_id_column else None
    contract_id = contract_id or None

    price_text = _clean_text(row.get(price_column, ""))
    if not price_text:
        return None

    failure_flags: list[str] = []
    unit_price: float | None = None
    currency: str | None = None

    if price_column in conflict_columns:
        failure_flags.append("MULTI_CURRENCY_CONFLICT")
        parse_error = True
    else:
        unit_price, currency = resolve_currency(price_text, price_column, document_currency_hint)
        if unit_price is None:
            parse_error = True
            failure_flags.append("PRICE_PARSE_ERROR")
        elif currency is None and row_currency_hint:
            currency = row_currency_hint

    row_confidence = _compute_row_confidence(
        item_description=item_description,
        unit_price=unit_price,
        currency=currency,
        quantity=quantity,
        item_inferred=layout.item_inferred,
        price_inferred=layout.price_inferred,
        parse_error=parse_error,
    )

    needs_review = (
        layout.item_inferred
        or layout.price_inferred
        or parse_error
        or unit_price is None
        or row_confidence < 0.70
    )

    return NormalizedLineItem(
        item_description=item_description,
        unit_raw=unit_raw,
        unit_price=unit_price,
        source_column=price_column,
        contract_id=contract_id,
        currency=currency,
        quantity=quantity,
        source_page=source_page,
        item_confidence=row_confidence,
        price_confidence=row_confidence,
        unit_confidence=row_confidence,
        needs_review=needs_review,
        extraction_method=method,
        failure_flags=failure_flags,
        row_confidence=row_confidence,
    )


def _coerce_mock_table(table: Any, index: int) -> RawTableResult:
    headers = list(getattr(table, "headers", []) or [])
    rows = list(getattr(table, "rows", []) or [])
    if not headers and rows and isinstance(rows[0], dict):
        return RawTableResult(
            source_page=getattr(table, "source_page", index),
            extraction_method=getattr(table, "extraction_method", "MOCK_TABLE"),
            raw_table_json=rows,
            table_confidence=float(getattr(table, "table_confidence", 0.50)),
            column_count=len(rows[0]) if rows else 0,
            row_count=len(rows),
            source_name=getattr(table, "source_name", f"mock_table_{index}"),
            source_row_count=len(rows),
            failure_flags=list(getattr(table, "failure_flags", []) or []),
        )

    sanitized_headers = _sanitize_headers(headers)
    raw_rows = [
        {
            sanitized_headers[column_index]: _clean_text(values[column_index]) if column_index < len(values) else ""
            for column_index in range(len(sanitized_headers))
        }
        for values in rows
    ]
    return RawTableResult(
        source_page=getattr(table, "source_page", index),
        extraction_method=getattr(table, "extraction_method", "MOCK_TABLE"),
        raw_table_json=raw_rows,
        table_confidence=float(getattr(table, "table_confidence", 0.50)),
        column_count=len(sanitized_headers),
        row_count=len(raw_rows),
        source_name=getattr(table, "source_name", f"mock_table_{index}"),
        source_row_count=len(raw_rows),
        failure_flags=list(getattr(table, "failure_flags", []) or []),
    )


def _coerce_raw_tables(raw_tables: list[Any]) -> list[RawTableResult]:
    coerced: list[RawTableResult] = []
    for index, table in enumerate(raw_tables, start=1):
        if isinstance(table, RawTableResult):
            coerced.append(table)
            continue
        if hasattr(table, "raw_table_json"):
            coerced.append(
                RawTableResult(
                    source_page=int(getattr(table, "source_page", index) or index),
                    extraction_method=str(getattr(table, "extraction_method", "")),
                    raw_table_json=list(getattr(table, "raw_table_json", []) or []),
                    table_confidence=float(getattr(table, "table_confidence", 0.50) or 0.50),
                    column_count=int(getattr(table, "column_count", 0) or 0),
                    row_count=int(getattr(table, "row_count", 0) or 0),
                    is_continuation=bool(getattr(table, "is_continuation", False)),
                    continued_from_index=getattr(table, "continued_from_index", None),
                    source_name=getattr(table, "source_name", None),
                    source_row_count=int(getattr(table, "source_row_count", 0) or 0),
                    failure_flags=list(getattr(table, "failure_flags", []) or []),
                )
            )
            continue
        coerced.append(_coerce_mock_table(table, index))
    return coerced


def _normalize_rows_from_table(
    table: RawTableResult,
    rows: list[dict[str, Any]],
    *,
    document_currency_hint: str | None,
) -> tuple[list[NormalizedLineItem], list[str], bool]:
    prepared_rows, headers, _source_headers, promoted_header_index = _prepare_table_rows(rows)
    failure_flags = list(getattr(table, "failure_flags", []) or [])
    if promoted_header_index >= 0:
        failure_flags.append(f"PROMOTED_EMBEDDED_HEADER:page={table.source_page}:row={promoted_header_index + 1}")

    usable_rows = [row for row in prepared_rows if not _is_blank_row(row)]
    if len(headers) < 2 or not usable_rows:
        return [], failure_flags, False

    column_roles = _map_column_roles(headers, usable_rows)
    layout = _resolve_table_layout(headers, usable_rows, column_roles)
    if not layout.price_columns or layout.item_column is None:
        failure_flags.append(f"POSITIONAL_FALLBACK_USED:page={table.source_page}")

    conflict_columns = _detect_price_column_conflicts(layout.price_columns, usable_rows)
    quantity_detected = layout.quantity_column is not None

    line_items: list[NormalizedLineItem] = []
    for row_index, row in enumerate(usable_rows, start=1):
        if _is_header_repeat(row, headers):
            failure_flags.append(f"SKIPPED_HEADER_REPEAT:page={table.source_page}:row={row_index}")
            continue
        if _is_subtotal_row(row):
            failure_flags.append(f"SKIPPED_SUBTOTAL_ROW:page={table.source_page}:row={row_index}")
            continue

        row_currency_hint = None
        if layout.currency_column:
            row_currency_hint = _find_currency_code(row.get(layout.currency_column, ""), kind="cells")
            if row_currency_hint is None:
                row_currency_hint = _find_currency_code(row.get(layout.currency_column, ""), kind="headers")

        for price_column in layout.price_columns:
            item = _build_line_item(
                row=row,
                layout=layout,
                price_column=price_column,
                row_currency_hint=row_currency_hint,
                document_currency_hint=document_currency_hint,
                source_page=int(table.source_page or 0),
                method=str(table.extraction_method or ""),
                conflict_columns=conflict_columns,
            )
            if item is None:
                continue
            if item.failure_flags:
                failure_flags.extend(
                    f"{flag}:page={table.source_page}:row={row_index}:column={price_column}"
                    for flag in item.failure_flags
                )
            line_items.append(item)

    return line_items, failure_flags, quantity_detected


def _compute_summary_confidence(line_items: list[NormalizedLineItem]) -> float:
    if not line_items:
        return 0.10
    return round(mean(item.row_confidence for item in line_items), 4)


def normalize_tables_detailed(
    raw_tables: List[Any],
    stitched: bool = True,
    document_text: str | None = None,
) -> NormalizationSummary:
    from backend.app.tools.contract_structuring.extractors.multi_page_stitcher import get_merged_rows

    tables = _coerce_raw_tables(list(raw_tables or []))
    failure_flags: list[str] = []
    all_rows: list[dict[str, Any]] = []
    for table in tables:
        all_rows.extend(table.raw_table_json or [])

    document_currency_hint = _detect_document_currency_hint(document_text, all_rows)
    line_items: list[NormalizedLineItem] = []
    source_rows = 0
    quantity_detected = False

    for index, table in enumerate(tables):
        if stitched and getattr(table, "is_continuation", False):
            continue

        rows = get_merged_rows(tables, index) if stitched else list(table.raw_table_json or [])
        if not rows:
            continue

        source_rows += max(int(getattr(table, "source_row_count", 0) or 0), len(rows))
        table_items, table_flags, table_has_quantity = _normalize_rows_from_table(
            table,
            rows,
            document_currency_hint=document_currency_hint,
        )
        quantity_detected = quantity_detected or table_has_quantity
        failure_flags.extend(table_flags)
        line_items.extend(table_items)

    summary = NormalizationSummary(
        line_items=line_items,
        failure_flags=list(dict.fromkeys(failure_flags)),
        confidence=_compute_summary_confidence(line_items),
        retained_rows=len(line_items),
        source_rows=source_rows,
        quantity_detected=quantity_detected,
        document_currency_hint=document_currency_hint,
    )
    return summary


def normalize_tables(
    raw_tables: List[Any],
    stitched: bool = True,
    document_text: str | None = None,
) -> List[NormalizedLineItem]:
    return normalize_tables_detailed(raw_tables, stitched=stitched, document_text=document_text).line_items


class TableNormalizer:
    """Compatibility wrapper used by the existing task flow and tests."""

    def classify_columns(self, rows: List[Dict]) -> Dict[str, str]:
        if not rows:
            return {}
        prepared_rows, headers, _source_headers, _promoted_header_index = _prepare_table_rows(rows)
        return _map_column_roles(headers, prepared_rows)

    def detect_column_roles(self, table_like) -> Dict[str, str]:
        if table_like is None:
            return {}
        if hasattr(table_like, "to_dict"):
            rows = table_like.to_dict("records")
        else:
            rows = table_like
        if not rows:
            return {}
        return self.classify_columns(rows)

    def normalize(self, raw_tables: List[Any], stitched: bool = True, document_text: str | None = None) -> List[NormalizedLineItem]:
        return normalize_tables(raw_tables, stitched=stitched, document_text=document_text)

    def normalize_table(self, stitched_table) -> List[NormalizedLineItem]:
        rows = getattr(stitched_table, "merged_rows", [])
        source_page = getattr(stitched_table, "source_page", 0) or 0
        if not rows:
            return []
        table = RawTableResult(
            source_page=source_page,
            extraction_method=str(getattr(stitched_table, "extraction_method", "")),
            raw_table_json=list(rows),
            table_confidence=0.50,
            column_count=len(rows[0]) if rows else 0,
            row_count=len(rows),
        )
        return normalize_tables([table], stitched=False)
