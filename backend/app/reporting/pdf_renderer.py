"""
LeakSight V1 — PDF Renderer

Source: docs/ARCHITECTURE.md (Section 6.7),
       docs/DECISIONS.md (ADR-007 — WeasyPrint locked)

Renders HTML templates to PDF bytes using WeasyPrint.

Callers must never reference WeasyPrint directly. All PDF generation
goes through this module so the renderer can be swapped without
touching assembler or endpoint code.

Standing rule: this module never queries the database.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger("leaksight.reporting.pdf_renderer")

# Template directory — sibling templates/ folder
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)


class ReportGenerationError(Exception):
    """Raised when PDF rendering fails.

    Callers should catch this and return a generic 500 message to the user.
    Never expose rendering internals or template errors to API consumers.
    """


def render_to_pdf(template_name: str, context: Dict[str, Any]) -> bytes:
    """Render a Jinja2 template with *context* and return PDF bytes.

    Parameters
    ----------
    template_name:
        Name of the template file inside the templates/ directory
        (e.g. ``"cfo_summary.html"`` or ``"evidence_pack.html"``).
    context:
        Template variables.  Keys must match the template's expected
        variables (run_id, currency, findings, etc.).

    Returns
    -------
    bytes
        Raw PDF content.  First bytes will be ``%PDF-``.

    Raises
    ------
    ReportGenerationError
        If template rendering or PDF conversion fails for any reason.
    """
    try:
        from weasyprint import HTML  # lazy import — ADR-007

        template = _jinja_env.get_template(template_name)
        html_string = template.render(**context)
        pdf_bytes: bytes = HTML(string=html_string).write_pdf()  # type: ignore[arg-type]
        return pdf_bytes
    except ReportGenerationError:
        raise
    except Exception as exc:
        logger.error(
            "PDF generation failed for template=%s: %s",
            template_name,
            type(exc).__name__,
            # Never log financial amounts or vendor names (logging rule)
        )
        raise ReportGenerationError(
            f"Failed to generate PDF from template '{template_name}'"
        ) from exc
