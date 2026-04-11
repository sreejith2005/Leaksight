"""Unit tests for Tool C document revalidation helpers."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from backend.app.tools.document_revalidation.date_extractor import extract_dates_from_parse
from backend.app.tools.document_revalidation.service import _compute_status


class TestComputeStatus:
    def test_valid_document(self):
        revalidation_doc = SimpleNamespace(
            expiry_date=date.today() + timedelta(days=180),
            has_expiry=True,
            alert_days_before=30,
        )

        assert _compute_status(revalidation_doc) == "VALID"

    def test_expiring_soon(self):
        revalidation_doc = SimpleNamespace(
            expiry_date=date.today() + timedelta(days=15),
            has_expiry=True,
            alert_days_before=30,
        )

        assert _compute_status(revalidation_doc) == "EXPIRING_SOON"

    def test_expired(self):
        revalidation_doc = SimpleNamespace(
            expiry_date=date.today() - timedelta(days=10),
            has_expiry=True,
            alert_days_before=30,
        )

        assert _compute_status(revalidation_doc) == "EXPIRED"

    def test_no_expiry(self):
        revalidation_doc = SimpleNamespace(
            expiry_date=None,
            has_expiry=False,
            alert_days_before=30,
        )

        assert _compute_status(revalidation_doc) == "NO_EXPIRY"

    def test_no_expiry_date(self):
        revalidation_doc = SimpleNamespace(
            expiry_date=None,
            has_expiry=True,
            alert_days_before=30,
        )

        assert _compute_status(revalidation_doc) == "REVALIDATION_PENDING"

    def test_boundary(self):
        revalidation_doc = SimpleNamespace(
            expiry_date=date.today() + timedelta(days=30),
            has_expiry=True,
            alert_days_before=30,
        )

        assert _compute_status(revalidation_doc) == "EXPIRING_SOON"


class TestDateExtractor:
    def test_extract_from_clauses(self):
        structured_output = {
            "clauses": [
                {"issue_date": "01/01/2024"},
                {"expiry_date": "31/12/2025"},
            ]
        }

        result = extract_dates_from_parse(structured_output)

        assert result["issue_date"] == date(2024, 1, 1)
        assert result["expiry_date"] == date(2025, 12, 31)
        assert result["confidence"] >= 0.90

    def test_extract_from_raw_text_regex(self):
        structured_output = {
            "raw_text": (
                "Certificate valid from 01/02/2025 for supplier onboarding. "
                "License valid till 05/03/2026 unless revoked earlier."
            )
        }

        result = extract_dates_from_parse(structured_output)

        assert result["issue_date"] == date(2025, 2, 1)
        assert result["expiry_date"] == date(2026, 3, 5)
        assert 0.50 <= result["confidence"] <= 0.85

    def test_empty_input(self):
        result = extract_dates_from_parse({})

        assert result == {
            "issue_date": None,
            "expiry_date": None,
            "confidence": 0.0,
        }

    def test_expiry_before_issue_discarded(self):
        structured_output = {
            "clauses": [
                {"issue_date": "15/05/2025"},
                {"expiry_date": "01/05/2025"},
            ]
        }

        result = extract_dates_from_parse(structured_output)

        assert result["issue_date"] is None
        assert result["expiry_date"] is None
        assert result["confidence"] <= 0.35

    def test_out_of_range_date_rejected(self):
        structured_output = {
            "clauses": [
                {"issue_date": "01/01/1985"},
            ]
        }

        result = extract_dates_from_parse(structured_output)

        assert result["issue_date"] is None
        assert result["expiry_date"] is None
        assert result["confidence"] == 0.0

    def test_confidence_hierarchy(self):
        clause_result = extract_dates_from_parse(
            {
                "clauses": [
                    {"issue_date": "01/01/2024"},
                    {"expiry_date": "31/12/2025"},
                ]
            }
        )
        regex_result = extract_dates_from_parse(
            {
                "raw_text": "Issued on 01/01/2024 and expires 31/12/2025.",
            }
        )

        assert clause_result["confidence"] > regex_result["confidence"]
