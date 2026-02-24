"""
LeakSight V1 — Vendor Name Normalization Service

Source: docs/RULES_ENGINE.md (vendor normalization section),
       docs/DECISIONS.md (ADR-002 — RapidFuzz over embeddings)

Provides two functions:
  - normalize_vendor_name: lowercase, strip legal suffixes, strip punctuation
  - generate_blocking_key: first significant token for candidate-set reduction
"""

import re

# Legal suffixes to strip — Indian and international variants.
# Ordered longest-first so "Private Limited" is stripped before "Private" or "Limited".
_LEGAL_SUFFIXES: list[str] = [
    r"private\s+limited",
    r"pvt\.?\s*ltd\.?",
    r"p\.?\s*ltd\.?",
    r"limited",
    r"ltd\.?",
    r"llp",
    r"llc",
    r"inc\.?",
    r"corp\.?",
    r"co\.?",
]

# Compiled pattern matching any legal suffix at end of string (case-insensitive)
_SUFFIX_PATTERN = re.compile(
    r"\b(?:" + "|".join(_LEGAL_SUFFIXES) + r")\s*$",
    re.IGNORECASE,
)

# Stopwords that are not significant tokens for blocking keys
_STOPWORDS: frozenset[str] = frozenset({"the", "and", "of", "&"})

# Punctuation to strip (everything except alphanumeric and whitespace)
_PUNCTUATION_PATTERN = re.compile(r"[^\w\s]", re.UNICODE)

# Multiple whitespace → single space
_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_vendor_name(raw_name: str) -> str:
    """Normalize a vendor name for matching.

    Converts to lowercase, strips legal suffixes (Pvt Ltd, Private Limited,
    Ltd, LLC, Inc, Corp, Co, LLP and Indian variants), strips punctuation,
    and strips extra whitespace.

    Args:
        raw_name: The raw vendor name as extracted from a document.

    Returns:
        Clean normalized vendor name.
    """
    if not raw_name:
        return ""

    name = raw_name.strip()

    # Strip legal suffixes (may need multiple passes for compound suffixes)
    for _ in range(3):
        new_name = _SUFFIX_PATTERN.sub("", name).strip()
        if new_name == name:
            break
        name = new_name

    # Lowercase
    name = name.lower()

    # Strip punctuation
    name = _PUNCTUATION_PATTERN.sub("", name)

    # Collapse whitespace
    name = _WHITESPACE_PATTERN.sub(" ", name).strip()

    return name


def generate_blocking_key(normalized_name: str) -> str:
    """Generate a blocking key from a normalized vendor name.

    Returns the first significant token — one that is not a common stopword
    (the, and, of, &). Used to reduce the candidate set before fuzzy matching.

    Args:
        normalized_name: A vendor name already passed through normalize_vendor_name.

    Returns:
        The first significant token, or empty string if none found.
    """
    if not normalized_name:
        return ""

    tokens = normalized_name.split()
    for token in tokens:
        if token not in _STOPWORDS:
            return token

    # All tokens are stopwords — return first token as fallback
    return tokens[0] if tokens else ""
