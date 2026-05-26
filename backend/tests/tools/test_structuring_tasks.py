"""Focused unit tests for Tool A structuring task helpers."""

from datetime import date

from backend.app.tools.contract_structuring import tasks


def test_parse_iso_date_handles_valid_and_invalid_values():
    assert tasks._parse_iso_date("2025-01-31") == date(2025, 1, 31)
    assert tasks._parse_iso_date("31-01-2025") is None
    assert tasks._parse_iso_date(None) is None


def test_resolve_validity_window_uses_clause_dates_when_line_item_dates_missing():
    valid_from, valid_to = tasks._resolve_validity_window(
        effective_dates=[None, None],
        expiry_dates=[None],
        clause_effective="2024-04-01",
        clause_expiry="2025-03-31",
    )

    assert valid_from == date(2024, 4, 1)
    assert valid_to == date(2025, 3, 31)


def test_resolve_validity_window_falls_back_to_default_when_no_dates_exist():
    valid_from, valid_to = tasks._resolve_validity_window(
        effective_dates=[None],
        expiry_dates=[None],
        clause_effective=None,
        clause_expiry=None,
    )

    assert valid_from == date.today()
    assert valid_to == tasks.DEFAULT_VALID_TO


def test_resolve_validity_window_corrects_inverted_ranges():
    valid_from, valid_to = tasks._resolve_validity_window(
        effective_dates=[date(2025, 6, 1)],
        expiry_dates=[date(2025, 5, 1)],
        clause_effective=None,
        clause_expiry=None,
    )

    assert valid_from == date(2025, 6, 1)
    assert valid_to == date(2025, 6, 1)
