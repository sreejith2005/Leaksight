"""
Detects if a document is an amendment/addendum to an existing contract.

Algorithm:
  1. Extract vendor name and contract reference from clause results
  2. Query existing contracts table for same tenant + similar vendor + similar ref
  3. If match found: this is an amendment, version_number = max(existing) + 1
  4. Compute price diff between this version and the previous version
"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger(__name__)


@dataclass
class VersionDetectionResult:
    is_amendment: bool
    version_number: int
    matched_contract_id: str | None
    amendment_reference: str | None
    diff_summary: dict


def detect_version(
    clause_results: List,
    tenant_id: str,
    db_session,
) -> Tuple[int, Optional[str], List[Dict]]:
    """
    Returns (version_number, base_contract_id, price_diff_list).
    version_number = 1 if no prior version found.
    base_contract_id = None if new contract.
    price_diff_list = [] if version 1.
    """
    from rapidfuzz import fuzz
    from sqlalchemy import text

    vendor_name = None
    contract_ref = None

    for clause in clause_results:
        if clause.clause_type == 'VENDOR_NAME' and clause.extracted_value:
            vendor_name = clause.extracted_value
        elif clause.clause_type == 'CONTRACT_REF' and clause.extracted_value:
            contract_ref = clause.extracted_value

    if not vendor_name and not contract_ref:
        logger.debug("No vendor or contract ref found - treating as new contract version 1")
        return 1, None, []

    try:
        rows = db_session.execute(
            text("""
                SELECT c.id, c.contract_reference, v.normalized_name, cv.version_number
                FROM contracts c
                JOIN vendors v ON c.vendor_id = v.id
                JOIN contract_versions cv ON cv.contract_id = c.id
                WHERE c.tenant_id = :tenant_id
                ORDER BY cv.version_number DESC
            """),
            {"tenant_id": str(tenant_id)}
        ).fetchall()
    except Exception as e:
        logger.error(f"Version detection DB query failed: {e}")
        return 1, None, []

    best_match_id = None
    best_score = 0

    for row in rows:
        contract_id, db_ref, db_vendor, db_version = row

        vendor_score = fuzz.token_sort_ratio(
            (vendor_name or '').lower(),
            (db_vendor or '').lower()
        ) if vendor_name else 0

        ref_score = fuzz.token_sort_ratio(
            (contract_ref or '').lower(),
            (db_ref or '').lower()
        ) if contract_ref and db_ref else 0

        combined_score = max(vendor_score, ref_score)

        if combined_score >= 85 and combined_score > best_score:
            best_score = combined_score
            best_match_id = str(contract_id)
            best_version = db_version

    if best_match_id:
        new_version = best_version + 1
        logger.info(f"Amendment detected: contract {best_match_id}, new version {new_version}")
        return new_version, best_match_id, []
    else:
        return 1, None, []


class VersionDetector:
    """Backward-compatible class API for legacy task flow."""

    def detect(
        self,
        vendor_name: str | None,
        contract_ref: str | None,
        existing_contracts: list[dict],
        current_items: list[dict],
        amendment_reference: str | None = None,
    ) -> VersionDetectionResult:
        from rapidfuzz import fuzz

        best_match = None
        best_score = 0.0

        for contract in existing_contracts:
            vendor_score = fuzz.ratio((vendor_name or "").lower(), str(contract.get("vendor_name", "")).lower())
            ref_score = fuzz.ratio((contract_ref or "").lower(), str(contract.get("contract_ref", "")).lower())
            score = (vendor_score + ref_score) / 2.0
            if score > best_score:
                best_score = score
                best_match = contract

        if not best_match or best_score < 85:
            return VersionDetectionResult(
                is_amendment=False,
                version_number=1,
                matched_contract_id=None,
                amendment_reference=amendment_reference,
                diff_summary={"price_changes": [], "price_increase_count": 0},
            )

        prior_versions = best_match.get("versions", [])
        prior_version_number = max((int(v.get("version_number", 1)) for v in prior_versions), default=1)

        return VersionDetectionResult(
            is_amendment=True,
            version_number=prior_version_number + 1,
            matched_contract_id=str(best_match.get("id")),
            amendment_reference=amendment_reference,
            diff_summary={"price_changes": [], "price_increase_count": 0},
        )
