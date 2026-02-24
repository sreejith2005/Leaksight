"""
LeakSight V1 — PDF Renderer Tests (Step 7.3)

WeasyPrint is mocked — tests verify:
 1. render_to_pdf returns bytes with %PDF- magic.
 2. ReportGenerationError is raised on rendering failure.
 3. Template rendering invokes Jinja2 then WeasyPrint.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Provide a fake weasyprint module so pdf_renderer can be imported
# even when WeasyPrint is not installed (Windows CI / local dev).
_fake_weasyprint = MagicMock()
sys.modules.setdefault("weasyprint", _fake_weasyprint)

from backend.app.reporting.pdf_renderer import (  # noqa: E402
    ReportGenerationError,
    render_to_pdf,
)


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

FAKE_PDF = b"%PDF-1.4 fake-pdf-content"

SAMPLE_CFO_CONTEXT = {
    "run_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "run_status": "completed",
    "report_generated_at": "2025-06-01T12:00:00Z",
    "total_leakage_amount": 15000.00,
    "currency": "INR",
    "leakage_by_vendor": [],
    "leakage_by_rule": [],
    "leakage_by_confidence_band": MagicMock(
        high_count=0, high_amount=0,
        medium_count=0, medium_amount=0,
        low_count=0, low_amount=0,
    ),
    "pending_review_count": 0,
    "pending_fx_rate_count": 0,
    "partial_success_notes": None,
}

SAMPLE_EVIDENCE_CONTEXT = {
    "run_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "tenant_name": "Acme Corp",
    "report_generated_at": "2025-06-01T12:00:00Z",
    "total_leakage_amount": 5000.00,
    "currency": "INR",
    "findings": [],
}


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRenderToPDF:
    """Tests for render_to_pdf function."""

    @patch("weasyprint.HTML")
    def test_returns_pdf_bytes_cfo_summary(self, mock_html_cls):
        """render_to_pdf for cfo_summary.html returns bytes with %PDF- magic."""
        mock_html_cls.return_value.write_pdf.return_value = FAKE_PDF

        result = render_to_pdf("cfo_summary.html", SAMPLE_CFO_CONTEXT)

        assert isinstance(result, bytes)
        assert result.startswith(b"%PDF-")
        mock_html_cls.assert_called_once()
        mock_html_cls.return_value.write_pdf.assert_called_once()

    @patch("weasyprint.HTML")
    def test_returns_pdf_bytes_evidence_pack(self, mock_html_cls):
        """render_to_pdf for evidence_pack.html returns bytes with %PDF- magic."""
        mock_html_cls.return_value.write_pdf.return_value = FAKE_PDF

        result = render_to_pdf("evidence_pack.html", SAMPLE_EVIDENCE_CONTEXT)

        assert isinstance(result, bytes)
        assert result.startswith(b"%PDF-")

    @patch("weasyprint.HTML")
    def test_weasyprint_receives_html_string(self, mock_html_cls):
        """WeasyPrint HTML() is called with string= keyword argument."""
        mock_html_cls.return_value.write_pdf.return_value = FAKE_PDF

        render_to_pdf("cfo_summary.html", SAMPLE_CFO_CONTEXT)

        call_kwargs = mock_html_cls.call_args
        # HTML(string=...) — string keyword must be present
        assert "string" in call_kwargs.kwargs or (
            len(call_kwargs.args) == 0 and "string" in call_kwargs.kwargs
        )
        html_string = call_kwargs.kwargs["string"]
        assert "LeakSight" in html_string

    @patch("weasyprint.HTML")
    def test_raises_report_generation_error_on_weasyprint_failure(
        self, mock_html_cls
    ):
        """If WeasyPrint raises, ReportGenerationError is raised."""
        mock_html_cls.return_value.write_pdf.side_effect = RuntimeError(
            "font not found"
        )

        with pytest.raises(ReportGenerationError, match="cfo_summary.html"):
            render_to_pdf("cfo_summary.html", SAMPLE_CFO_CONTEXT)

    def test_raises_report_generation_error_on_bad_template(self):
        """If template name is invalid, ReportGenerationError is raised."""
        with pytest.raises(ReportGenerationError):
            render_to_pdf("nonexistent_template.html", {})

    @patch("weasyprint.HTML")
    def test_re_raises_explicit_report_generation_error(self, mock_html_cls):
        """If ReportGenerationError is raised inside, it is not double-wrapped."""
        mock_html_cls.return_value.write_pdf.side_effect = (
            ReportGenerationError("already wrapped")
        )

        with pytest.raises(ReportGenerationError, match="already wrapped"):
            render_to_pdf("cfo_summary.html", SAMPLE_CFO_CONTEXT)
