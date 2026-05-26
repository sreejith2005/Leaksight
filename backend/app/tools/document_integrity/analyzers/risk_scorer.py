"""Risk scoring for Tool B."""

from __future__ import annotations

from typing import Any


def risk_level_from_score(score: int | None) -> str | None:
    """Map a numeric score to LOW, MEDIUM, or HIGH."""
    if score is None:
        return None
    if score <= 30:
        return "LOW"
    if score <= 69:
        return "MEDIUM"
    return "HIGH"


class RiskScorer:
    """Compute deterministic Tool B risk scores."""

    def score(
        self,
        hash_result: dict[str, Any],
        metadata: dict[str, Any],
        numeric_changes: list[dict[str, Any]],
    ) -> tuple[int, list[str]]:
        """Return the integer score and plain-English flags."""
        score = 0
        flags: list[str] = []
        hash_status = str(hash_result.get("status") or "INCONCLUSIVE")

        if hash_status == "MODIFIED":
            score += 65 if numeric_changes else 40
            flags.append("Document hash has changed since baseline")
        elif hash_status == "INCONCLUSIVE":
            score += 20
            flags.append("Hash comparison was inconclusive")

        gt_10_bonus = 0
        gt_100_bonus = 0
        for change in numeric_changes:
            change_pct = float(change.get("change_pct") or 0)
            if change_pct > 10:
                gt_10_bonus = min(20, gt_10_bonus + 10)
            if change_pct > 100:
                gt_100_bonus = min(25, gt_100_bonus + 15)

        score += gt_10_bonus + gt_100_bonus

        if numeric_changes:
            largest_change = max(numeric_changes, key=lambda item: float(item.get("change_pct") or 0))
            flags.append(
                f"{len(numeric_changes)} numeric values changed "
                f"(largest: {largest_change['previous_value']} -> {largest_change['current_value']})"
            )

        anomaly_messages = {
            "modification_date_precedes_creation_date": (
                20,
                "Metadata modification date precedes creation date",
            ),
            "unusually_old_modification_date": (
                10,
                "Metadata shows an unusually old modification date",
            ),
            "missing_author_metadata": (
                5,
                "Metadata author field is missing",
            ),
            "software_mismatch_for_invoice": (
                10,
                "Editing software looks inconsistent for an invoice document",
            ),
        }

        for anomaly in metadata.get("anomalies", []):
            rule = anomaly_messages.get(str(anomaly))
            if rule is None:
                continue
            score += rule[0]
            flags.append(rule[1])

        return min(100, score), flags
