"""
LeakSight V1 — Template Rendering Tests (Step 7.2)

Tests that Jinja2 templates render correct HTML from assembler data
structures.  No WeasyPrint is invoked — tests verify the HTML string only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from jinja2 import Environment, FileSystemLoader

# ─── Template directory setup ───────────────────────────────────────────
TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "reporting"
    / "templates"
)

env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


# ═══════════════════════════════════════════════════════════════════════
# Helpers — build sample context dicts matching assembler dataclasses
# ═══════════════════════════════════════════════════════════════════════

class _Obj:
    """Lightweight object that exposes dict keys as attributes (for Jinja2)."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def _cfo_context(
    *,
    partial_success_notes: str | None = None,
    vendor_count: int = 2,
    pending_fx_rate_count: int = 0,
) -> dict:
    vendors = [
        _Obj(vendor_name="Tata Steel", total_amount=Decimal("5000.00"), record_count=2),
        _Obj(vendor_name="JSW Steel", total_amount=Decimal("10000.00"), record_count=3),
    ][:vendor_count]

    rules = [
        _Obj(rule_type="price_mismatch", total_amount=Decimal("12000.00"), record_count=4),
        _Obj(rule_type="duplicate_invoice", total_amount=Decimal("3000.00"), record_count=1),
    ]

    bands = _Obj(
        high_count=3, high_amount=Decimal("11000.00"),
        medium_count=1, medium_amount=Decimal("3000.00"),
        low_count=1, low_amount=Decimal("1000.00"),
    )

    return {
        "run_id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "run_status": "completed",
        "report_generated_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "total_leakage_amount": Decimal("15000.00"),
        "currency": "INR",
        "leakage_by_vendor": vendors,
        "leakage_by_rule": rules,
        "leakage_by_confidence_band": bands,
        "pending_review_count": 2,
        "pending_fx_rate_count": pending_fx_rate_count,
        "partial_success_notes": partial_success_notes,
    }


def _evidence_finding(
    *,
    unit_conversion: bool = False,
    fx_rate: bool = False,
) -> _Obj:
    finding = _Obj(
        record_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        leakage_type="price_mismatch",
        amount=Decimal("5000.00"),
        currency="INR",
        confidence=0.92,
        confidence_label="High",
        explanation="Invoiced at 110/kg vs contracted 100/kg",
        vendor_name="Tata Steel",
        invoice_number="INV-001",
        invoice_date=date(2025, 3, 15),
        invoice_line_item=_Obj(
            item_desc="Hot Rolled Coil",
            quantity=Decimal("500"),
            unit="kg",
            unit_price=Decimal("110.00"),
        ),
        contract_reference=_Obj(
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
            unit_price=Decimal("100.00"),
            unit="kg",
            version_number=None,
        ),
        rule_applied="rule_1_price_mismatch",
        unit_conversion_applied=unit_conversion,
        unit_conversion_details=(
            _Obj(from_unit="ton", to_unit="kg", factor="1000", source="built-in")
            if unit_conversion
            else None
        ),
        fx_rate_applied=(
            _Obj(from_currency="USD", to_currency="INR", rate="83.50",
                 rate_date="2025-03-15", source="ECB")
            if fx_rate
            else None
        ),
    )
    return finding


def _evidence_context(findings_count: int = 2, *, unit_conversion: bool = False) -> dict:
    findings = []
    for i in range(findings_count):
        f = _evidence_finding(unit_conversion=(unit_conversion and i == 0))
        # make each finding slightly different
        f.record_id = UUID(f"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb{i}")
        f.amount = Decimal(str(5000 + i * 2000))
        findings.append(f)

    total = sum(f.amount for f in findings)
    return {
        "run_id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "tenant_name": "Acme Corp",
        "report_generated_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "total_leakage_amount": total,
        "currency": "INR",
        "findings": findings,
    }


# ═══════════════════════════════════════════════════════════════════════
# CFO Summary Template Tests
# ═══════════════════════════════════════════════════════════════════════


class TestCFOSummaryTemplate:
    """Render cfo_summary.html with sample data."""

    def test_render_with_sample_data(self):
        """Renders complete CFO summary with vendor/rule/confidence tables."""
        tmpl = env.get_template("cfo_summary.html")
        ctx = _cfo_context()
        html = tmpl.render(**ctx)

        # Header present
        assert "LeakSight" in html
        assert "Commercial Leakage Analysis" in html
        assert str(ctx["run_id"]) in html

        # Executive summary — total amount formatted
        assert "15,000.00" in html
        assert "INR" in html

        # Vendor rows
        assert "Tata Steel" in html
        assert "JSW Steel" in html

        # Rule rows
        assert "price_mismatch" in html
        assert "duplicate_invoice" in html

        # Confidence bands
        assert "High" in html or "90%" in html
        assert "Medium" in html or "70%" in html

        # Footer disclaimer
        assert "accepted findings only" in html

    def test_partial_success_notes_present(self):
        """When partial_success_notes is set, notice box renders."""
        tmpl = env.get_template("cfo_summary.html")
        ctx = _cfo_context(partial_success_notes="3 invoices failed parsing")
        html = tmpl.render(**ctx)

        assert "Partial Success" in html
        assert "3 invoices failed parsing" in html

    def test_partial_success_notes_absent(self):
        """When partial_success_notes is None, notice box does NOT render."""
        tmpl = env.get_template("cfo_summary.html")
        ctx = _cfo_context(partial_success_notes=None)
        html = tmpl.render(**ctx)

        assert "Partial Success" not in html

    def test_pending_fx_count_shown(self):
        """When pending_fx_rate_count > 0, the FX pending note appears."""
        tmpl = env.get_template("cfo_summary.html")
        ctx = _cfo_context(pending_fx_rate_count=5)
        html = tmpl.render(**ctx)

        assert "5" in html
        assert "pending FX rate" in html


# ═══════════════════════════════════════════════════════════════════════
# Evidence Pack Template Tests
# ═══════════════════════════════════════════════════════════════════════


class TestEvidencePackTemplate:
    """Render evidence_pack.html with sample data."""

    def test_render_two_findings(self):
        """Evidence pack with two findings renders cover, TOC, and sections."""
        tmpl = env.get_template("evidence_pack.html")
        ctx = _evidence_context(findings_count=2)
        html = tmpl.render(**ctx)

        # Cover page
        assert "Evidence Pack" in html
        assert "Acme Corp" in html
        assert str(ctx["run_id"]) in html

        # TOC
        assert "Table of Contents" in html

        # Finding sections — both present
        assert "Finding #1" in html
        assert "Finding #2" in html

        # Invoice details
        assert "INV-001" in html
        assert "Hot Rolled Coil" in html

        # Contract reference
        assert "2025-01-01" in html or "Jan" in html

        # Explanation
        assert "110/kg" in html

        # Footer
        assert "accepted findings only" in html

    def test_render_zero_findings(self):
        """When no findings exist, 'no findings' message renders."""
        tmpl = env.get_template("evidence_pack.html")
        ctx = _evidence_context(findings_count=0)
        html = tmpl.render(**ctx)

        assert "No Confirmed Leakage Findings" in html
        assert "Finding #1" not in html
        assert "Table of Contents" not in html

    def test_unit_conversion_present(self):
        """When unit conversion applied, the note box renders."""
        tmpl = env.get_template("evidence_pack.html")
        ctx = _evidence_context(findings_count=1, unit_conversion=True)
        html = tmpl.render(**ctx)

        assert "Unit Conversion Applied" in html
        assert "ton" in html
        assert "kg" in html
        assert "1000" in html

    def test_unit_conversion_absent(self):
        """When no unit conversion, the note box does NOT render."""
        tmpl = env.get_template("evidence_pack.html")
        ctx = _evidence_context(findings_count=1, unit_conversion=False)
        html = tmpl.render(**ctx)

        assert "Unit Conversion Applied" not in html

    def test_fx_rate_present(self):
        """When FX rate applied, the FX note box renders."""
        tmpl = env.get_template("evidence_pack.html")
        finding = _evidence_finding(fx_rate=True)
        ctx = {
            "run_id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            "tenant_name": "Acme Corp",
            "report_generated_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            "total_leakage_amount": Decimal("5000.00"),
            "currency": "INR",
            "findings": [finding],
        }
        html = tmpl.render(**ctx)

        assert "FX Conversion Applied" in html
        assert "USD" in html
        assert "83.50" in html

    def test_fx_rate_absent(self):
        """When no FX rate, the FX note box does NOT render."""
        tmpl = env.get_template("evidence_pack.html")
        finding = _evidence_finding(fx_rate=False)
        ctx = {
            "run_id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            "tenant_name": "Acme Corp",
            "report_generated_at": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            "total_leakage_amount": Decimal("5000.00"),
            "currency": "INR",
            "findings": [finding],
        }
        html = tmpl.render(**ctx)

        assert "FX Conversion Applied" not in html
