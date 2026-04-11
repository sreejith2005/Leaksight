"""Date extraction helpers for Tool C revalidation records."""

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as date_parser
import spacy

try:
    _nlp = spacy.load("en_core_web_sm")
except Exception:
    _nlp = None


_MIN_DATE = date(1990, 1, 1)
_MAX_DATE = date(2099, 12, 31)
_STEP1_ISSUE_KEYS = ("effective_date", "issue_date", "valid_from")
_STEP1_EXPIRY_KEYS = ("expiry_date", "valid_to", "expiry", "valid_until")
_ISSUE_KEYWORDS = (
    "issue",
    "issued",
    "valid from",
    "date of issue",
    "effective",
    "certificate date",
)
_EXPIRY_KEYWORDS = (
    "expir",
    "valid till",
    "valid until",
    "renewal",
    "validity",
    "expires",
)
_DATE_PATTERNS = (
    r"\b(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})\b",
    r"\b(\d{1,2}\s+\w+\s+\d{4})\b",
)


def _normalize_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        candidate = value.date()
    elif isinstance(value, date):
        candidate = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            candidate = date_parser.parse(text, dayfirst=True, fuzzy=False).date()
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None

    if candidate < _MIN_DATE or candidate > _MAX_DATE:
        return None
    return candidate


def _finalize(issue_date: date | None, expiry_date: date | None, confidence: float) -> dict:
    if issue_date is not None and expiry_date is not None and expiry_date < issue_date:
        return {
            "issue_date": None,
            "expiry_date": None,
            "confidence": 0.30,
        }
    return {
        "issue_date": issue_date,
        "expiry_date": expiry_date,
        "confidence": confidence,
    }


def _extract_clause_value(record: dict, aliases: tuple[str, ...]) -> object | None:
    for alias in aliases:
        if alias in record:
            return record.get(alias)

    record_key = str(
        record.get("key")
        or record.get("name")
        or record.get("clause_type")
        or record.get("type")
        or record.get("field")
        or ""
    ).strip().lower()
    if record_key in aliases:
        return (
            record.get("value")
            or record.get("extracted_value")
            or record.get("text")
            or record.get("raw_text")
        )

    return None


def _extract_from_step1(structured_output: dict) -> dict | None:
    issue_date = None
    expiry_date = None

    for key in _STEP1_ISSUE_KEYS:
        issue_date = _normalize_date(structured_output.get(key))
        if issue_date is not None:
            break

    for key in _STEP1_EXPIRY_KEYS:
        expiry_date = _normalize_date(structured_output.get(key))
        if expiry_date is not None:
            break

    clauses = structured_output.get("clauses")
    if isinstance(clauses, list):
        for clause in clauses:
            if not isinstance(clause, dict):
                continue
            if issue_date is None:
                issue_date = _normalize_date(_extract_clause_value(clause, _STEP1_ISSUE_KEYS))
            if expiry_date is None:
                expiry_date = _normalize_date(_extract_clause_value(clause, _STEP1_EXPIRY_KEYS))
            if issue_date is not None and expiry_date is not None:
                break

    if issue_date is None and expiry_date is None:
        return None

    confidence = 0.95 if issue_date is not None and expiry_date is not None else 0.80
    return _finalize(issue_date, expiry_date, confidence)


def _extract_keyword_date(raw_text: str, keywords: tuple[str, ...]) -> date | None:
    for keyword in keywords:
        pattern = re.compile(
            rf"(?is)\b{re.escape(keyword)}\b[^\n\r]{{0,80}}?({_DATE_PATTERNS[0]}|{_DATE_PATTERNS[1]})"
        )
        for match in pattern.finditer(raw_text):
            candidate_text = match.group(1)
            candidate = _normalize_date(candidate_text)
            if candidate is not None:
                return candidate

    lowered = raw_text.lower()
    for keyword in keywords:
        start = 0
        while True:
            index = lowered.find(keyword, start)
            if index < 0:
                break
            snippet = raw_text[index:index + 120]
            for pattern in _DATE_PATTERNS:
                date_match = re.search(pattern, snippet)
                if date_match:
                    candidate = _normalize_date(date_match.group(1))
                    if candidate is not None:
                        return candidate
            start = index + len(keyword)

    return None


def _extract_from_step2(structured_output: dict) -> dict | None:
    raw_text = structured_output.get("raw_text") or structured_output.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None

    issue_date = _extract_keyword_date(raw_text, _ISSUE_KEYWORDS)
    expiry_date = _extract_keyword_date(raw_text, _EXPIRY_KEYWORDS)
    if issue_date is None and expiry_date is None:
        return None

    confidence = 0.75 if issue_date is not None and expiry_date is not None else 0.55
    return _finalize(issue_date, expiry_date, confidence)


def _extract_from_step3(structured_output: dict) -> dict | None:
    if _nlp is None:
        return None

    raw_text = structured_output.get("raw_text") or structured_output.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None

    doc = _nlp(raw_text[:5000])
    parsed_dates = sorted(
        {
            candidate
            for ent in doc.ents
            if ent.label_ == "DATE"
            for candidate in [_normalize_date(ent.text)]
            if candidate is not None
        }
    )
    if not parsed_dates:
        return None

    issue_date = parsed_dates[0]
    expiry_date = parsed_dates[-1] if len(parsed_dates) > 1 else None
    return _finalize(issue_date, expiry_date, 0.40)


def extract_dates_from_parse(structured_output: dict) -> dict:
    """Extract issue/expiry dates from an existing parsed document payload."""
    if not isinstance(structured_output, dict) or not structured_output:
        return {
            "issue_date": None,
            "expiry_date": None,
            "confidence": 0.0,
        }

    for extractor in (_extract_from_step1, _extract_from_step2, _extract_from_step3):
        result = extractor(structured_output)
        if result is not None:
            return result

    return {
        "issue_date": None,
        "expiry_date": None,
        "confidence": 0.0,
    }
