"""
Clause extractor - finds key commercial terms in contract text.

Uses:
  - spaCy en_core_web_sm for sentence splitting and NER (loaded once at module level)
  - python-dateutil for robust date parsing
  - Regex + keyword windows for clause classification

Clause types:
  EFFECTIVE_DATE, EXPIRY_DATE, AMENDMENT_REF, ESCALATION, VENDOR_NAME, CONTRACT_REF
"""
import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    import spacy
    _nlp = spacy.load('en_core_web_sm')
    logger.info("spaCy model loaded")
except Exception as e:
    _nlp = None
    logger.warning(f"spaCy model not available: {e}")

CLAUSE_KEYWORDS = {
    'EFFECTIVE_DATE': [
        'effective from', 'effective date', 'commencement date',
        'w.e.f', 'with effect from', 'commencing from', 'start date'
    ],
    'EXPIRY_DATE': [
        'valid until', 'expiry date', 'expires on', 'validity period',
        'contract end', 'end date', 'termination date', 'valid through'
    ],
    'AMENDMENT_REF': [
        'amendment no', 'amendment number', 'addendum', 'amendment to contract',
        'variation order', 'change order', 'corrigendum'
    ],
    'ESCALATION': [
        'price escalation', 'rate revision', 'annual increase',
        'escalation clause', 'price increase', 'rate escalation'
    ],
}

CONTRACT_REF_PATTERN = re.compile(
    r'(?:contract\s*(?:no|number|ref|reference)[.:\s]+|agreement\s*(?:no|ref)[.:\s]+|CTR[-/])'
    r'([A-Z0-9][-A-Z0-9/]{2,30})',
    re.IGNORECASE
)


def extract_clauses(text: str, document_path: str = "") -> List:
    """
    Extract commercial clauses from document text.
    Returns list of ExtractedClauseResult.
    """
    from backend.app.tools.contract_structuring.extractors.base_extractor import ExtractedClauseResult

    if not text or not text.strip():
        return []

    results = []
    sentences = _split_sentences(text)

    for page_estimate, sentence in enumerate(sentences, 1):
        sentence_clean = sentence.strip()
        if len(sentence_clean) < 10:
            continue

        for clause_type, keywords in CLAUSE_KEYWORDS.items():
            sentence_lower = sentence_clean.lower()
            matched_keyword = None
            for kw in keywords:
                if kw in sentence_lower:
                    matched_keyword = kw
                    break

            if not matched_keyword:
                continue

            extracted_value = None
            confidence = 0.85

            if clause_type in ('EFFECTIVE_DATE', 'EXPIRY_DATE'):
                extracted_value, date_conf = _extract_date(sentence_clean)
                confidence = min(0.95, confidence * date_conf) if extracted_value else 0.5

            elif clause_type == 'AMENDMENT_REF':
                extracted_value = _extract_amendment_ref(sentence_clean)
                confidence = 0.9 if extracted_value else 0.6

            elif clause_type == 'ESCALATION':
                extracted_value = sentence_clean[:200]
                confidence = 0.75

            needs_review = confidence < 0.7 or extracted_value is None

            results.append(ExtractedClauseResult(
                clause_type=clause_type,
                raw_text=sentence_clean[:500],
                extracted_value=extracted_value,
                source_page=_estimate_page(page_estimate, len(sentences)),
                confidence=confidence,
                needs_review=needs_review,
            ))

    for match in CONTRACT_REF_PATTERN.finditer(text[:5000]):
        results.append(ExtractedClauseResult(
            clause_type='CONTRACT_REF',
            raw_text=match.group(0),
            extracted_value=match.group(1).strip(),
            source_page=1,
            confidence=0.95,
            needs_review=False,
        ))

    vendor_clauses = _extract_vendor_names(text)
    results.extend(vendor_clauses)

    results = _deduplicate(results)

    return results


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using spaCy if available, else simple split."""
    if _nlp is not None:
        try:
            doc = _nlp(text[:50000])
            return [sent.text for sent in doc.sents]
        except Exception as e:
            logger.debug(f"spaCy sentence split failed: {e}")
    return [s.strip() for s in re.split(r'[.\n]', text) if s.strip()]


def _extract_date(text: str):
    """Extract a date from text. Returns (ISO_string, confidence) or (None, 0.0)."""
    try:
        from dateutil import parser as dateparser
        from dateutil.parser import ParserError

        if _nlp is not None:
            doc = _nlp(text)
            for ent in doc.ents:
                if ent.label_ == 'DATE':
                    try:
                        parsed = dateparser.parse(ent.text, dayfirst=True)
                        if parsed and 1990 <= parsed.year <= 2050:
                            return parsed.date().isoformat(), 0.95
                    except (ParserError, ValueError):
                        pass

        date_patterns = [
            r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b',
            r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
            r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    parsed = dateparser.parse(match.group(1), dayfirst=True)
                    if parsed and 1990 <= parsed.year <= 2050:
                        return parsed.date().isoformat(), 0.80
                except (ParserError, ValueError):
                    pass
    except Exception as e:
        logger.debug(f"Date extraction failed: {e}")

    return None, 0.0


def _extract_amendment_ref(text: str) -> Optional[str]:
    """Extract amendment reference number from text."""
    patterns = [
        r'amendment\s+(?:no\.?|number)?\s*[:#]?\s*(\d+)',
        r'addendum\s+(?:no\.?|number)?\s*[:#]?\s*(\d+)',
        r'variation\s+order\s+(?:no\.?|number)?\s*[:#]?\s*(\w+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_vendor_names(text: str) -> List:
    """Extract vendor/organization names from first 3 pages using spaCy NER."""
    from backend.app.tools.contract_structuring.extractors.base_extractor import ExtractedClauseResult

    results = []
    if _nlp is None:
        return results

    try:
        excerpt = text[:3000]
        doc = _nlp(excerpt)
        seen = set()
        for ent in doc.ents:
            if ent.label_ == 'ORG' and len(ent.text.strip()) > 3:
                name = ent.text.strip()
                if name not in seen:
                    seen.add(name)
                    results.append(ExtractedClauseResult(
                        clause_type='VENDOR_NAME',
                        raw_text=ent.sent.text.strip()[:200],
                        extracted_value=name,
                        source_page=1,
                        confidence=0.75,
                        needs_review=True,
                    ))
    except Exception as e:
        logger.debug(f"Vendor NER failed: {e}")

    return results[:3]


def _estimate_page(sentence_index: int, total_sentences: int) -> int:
    """Rough page estimate based on sentence position."""
    if total_sentences == 0:
        return 1
    return max(1, round(sentence_index / total_sentences * 10))


def _deduplicate(results: List) -> List:
    """Keep highest confidence result per clause_type."""
    best = {}
    for r in results:
        if r.clause_type not in best or r.confidence > best[r.clause_type].confidence:
            best[r.clause_type] = r
    final = []
    vendor_count = 0
    for r in results:
        if r.clause_type == 'VENDOR_NAME':
            if vendor_count < 3:
                final.append(r)
                vendor_count += 1
        elif r == best.get(r.clause_type):
            final.append(r)
    return final


class ClauseExtractor:
    """Backward-compatible wrapper for existing class-based extraction flows."""

    def extract(self, text: str, source_page: int = None) -> List:
        return extract_clauses(text)
