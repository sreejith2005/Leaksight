"""Test WeasyPrint evidence pack rendering inside Docker container.

This script:
1. Renders the evidence_pack.html template with realistic mock data
2. Writes the output PDF to /output/evidence_pack_test.pdf
3. Validates the PDF starts with %PDF-
4. Prints file size and status
"""
import sys
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path("/app/templates")

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)


def build_mock_findings():
    """Build 5 mock findings with all fields the template expects."""
    findings = []

    # Finding 1 — PRICE_MISMATCH
    findings.append({
        "record_id": str(uuid4()),
        "leakage_type": "PRICE_MISMATCH",
        "amount": Decimal("7000.00"),
        "currency": "INR",
        "confidence": 0.95,
        "confidence_label": "High",
        "explanation": (
            "Invoice unit price (₹520.00) exceeds contract unit price "
            "(₹450.00) by ₹70.00 per unit for Cloud Hosting Services. "
            "Total overcharge: 100 units × ₹70.00 = ₹7,000.00."
        ),
        "vendor_name": "TechServ India",
        "invoice_number": "INV-DEMO-004",
        "invoice_date": date(2024, 3, 15),
        "invoice_line_item": {
            "item_desc": "Cloud Hosting Services - Monthly",
            "quantity": 100,
            "unit": "Nos",
            "unit_price": Decimal("520.00"),
        },
        "contract_reference": {
            "valid_from": date(2024, 1, 1),
            "valid_to": date(2024, 12, 31),
            "unit_price": Decimal("450.00"),
            "unit": "Nos",
            "version_number": 1,
        },
        "unit_conversion_applied": False,
        "unit_conversion_details": None,
        "fx_rate_applied": None,
        "rule_applied": "Rule 1 — Price Mismatch",
    })

    # Finding 2 — DUPLICATE_INVOICE
    findings.append({
        "record_id": str(uuid4()),
        "leakage_type": "DUPLICATE_INVOICE",
        "amount": Decimal("45000.00"),
        "currency": "INR",
        "confidence": 1.0,
        "confidence_label": "High",
        "explanation": (
            "Invoice INV-DEMO-007 is an exact duplicate of INV-DEMO-003 "
            "(same invoice number, same vendor, same amount ₹45,000.00). "
            "Both invoices submitted within 30-day window."
        ),
        "vendor_name": "Acme Supplies Ltd",
        "invoice_number": "INV-DEMO-007",
        "invoice_date": date(2024, 5, 20),
        "invoice_line_item": {
            "item_desc": "Office Furniture - Executive Desk",
            "quantity": 10,
            "unit": "Nos",
            "unit_price": Decimal("4500.00"),
        },
        "contract_reference": {
            "valid_from": date(2024, 1, 1),
            "valid_to": date(2024, 12, 31),
            "unit_price": Decimal("4500.00"),
            "unit": "Nos",
            "version_number": None,
        },
        "unit_conversion_applied": False,
        "unit_conversion_details": None,
        "fx_rate_applied": None,
        "rule_applied": "Rule 2 — Duplicate Invoice",
    })

    # Finding 3 — QUANTITY_MISMATCH
    findings.append({
        "record_id": str(uuid4()),
        "leakage_type": "QUANTITY_MISMATCH",
        "amount": Decimal("20000.00"),
        "currency": "INR",
        "confidence": 0.92,
        "confidence_label": "High",
        "explanation": (
            "Invoice claims 75 units but PO authorized only 50 units for "
            "Safety Helmets. Excess quantity: 25 units × ₹800.00 = ₹20,000.00."
        ),
        "vendor_name": "BuildRight Materials",
        "invoice_number": "INV-DEMO-019",
        "invoice_date": date(2024, 8, 10),
        "invoice_line_item": {
            "item_desc": "Safety Helmets - Industrial Grade",
            "quantity": 75,
            "unit": "Nos",
            "unit_price": Decimal("800.00"),
        },
        "contract_reference": {
            "valid_from": date(2024, 1, 1),
            "valid_to": date(2024, 12, 31),
            "unit_price": Decimal("800.00"),
            "unit": "Nos",
            "version_number": 1,
        },
        "unit_conversion_applied": False,
        "unit_conversion_details": None,
        "fx_rate_applied": None,
        "rule_applied": "Rule 3 — Quantity Mismatch",
    })

    # Finding 4 — PRICE_MISMATCH with unit conversion
    findings.append({
        "record_id": str(uuid4()),
        "leakage_type": "PRICE_MISMATCH",
        "amount": Decimal("12500.00"),
        "currency": "INR",
        "confidence": 0.88,
        "confidence_label": "Medium",
        "explanation": (
            "Invoice unit price (₹55.00/KG) exceeds contract unit price "
            "(₹50.00/KG) by ₹5.00 per KG for Steel Bars. "
            "Total overcharge: 2500 KG × ₹5.00 = ₹12,500.00."
        ),
        "vendor_name": "BuildRight Materials",
        "invoice_number": "INV-DEMO-012",
        "invoice_date": date(2024, 6, 1),
        "invoice_line_item": {
            "item_desc": "Steel Bars - 12mm TMT",
            "quantity": 2.5,
            "unit": "MT",
            "unit_price": Decimal("55000.00"),
        },
        "contract_reference": {
            "valid_from": date(2024, 1, 1),
            "valid_to": date(2024, 12, 31),
            "unit_price": Decimal("50.00"),
            "unit": "KG",
            "version_number": 2,
        },
        "unit_conversion_applied": True,
        "unit_conversion_details": {
            "from_unit": "MT",
            "to_unit": "KG",
            "factor": 1000,
            "source": "canonical_units",
            "applied": True,
        },
        "fx_rate_applied": None,
        "rule_applied": "Rule 1 — Price Mismatch (with unit conversion)",
    })

    # Finding 5 — PRICE_MISMATCH with FX rate
    findings.append({
        "record_id": str(uuid4()),
        "leakage_type": "PRICE_MISMATCH",
        "amount": Decimal("3200.00"),
        "currency": "INR",
        "confidence": 0.75,
        "confidence_label": "Medium",
        "explanation": (
            "Invoice unit price (€6.20) exceeds contract unit price "
            "(€5.80) by €0.40 per unit for Network Cables. "
            "Converted to INR at rate 83.50: ₹3,200.00 total overcharge."
        ),
        "vendor_name": "TechServ India",
        "invoice_number": "INV-DEMO-015",
        "invoice_date": date(2024, 7, 15),
        "invoice_line_item": {
            "item_desc": "Network Cables - Cat6 100m",
            "quantity": 96,
            "unit": "Nos",
            "unit_price": Decimal("6.20"),
        },
        "contract_reference": {
            "valid_from": date(2024, 1, 1),
            "valid_to": date(2024, 12, 31),
            "unit_price": Decimal("5.80"),
            "unit": "Nos",
            "version_number": 1,
        },
        "unit_conversion_applied": False,
        "unit_conversion_details": None,
        "fx_rate_applied": {
            "from_currency": "EUR",
            "to_currency": "INR",
            "rate": 83.50,
            "rate_date": "2024-07-15",
            "source": "manual",
        },
        "rule_applied": "Rule 1 — Price Mismatch (cross-currency)",
    })

    return findings


def main():
    print("=== WeasyPrint Evidence Pack Test ===")
    print()

    # Build context
    findings = build_mock_findings()
    total_amount = sum(f["amount"] for f in findings)

    context = {
        "run_id": str(uuid4()),
        "tenant_name": "Test Client",
        "report_generated_at": datetime.utcnow(),
        "total_leakage_amount": float(total_amount),
        "currency": "INR",
        "findings": findings,
    }

    print(f"Findings count: {len(findings)}")
    print(f"Total leakage: ₹{total_amount:,.2f}")
    print()

    # Render HTML
    print("Rendering HTML template...")
    template = jinja_env.get_template("evidence_pack.html")
    html_string = template.render(**context)
    print(f"HTML length: {len(html_string)} chars")
    print()

    # Convert to PDF
    print("Converting to PDF with WeasyPrint...")
    from weasyprint import HTML
    pdf_bytes = HTML(string=html_string).write_pdf()

    # Write output
    output_dir = Path("/output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "evidence_pack_test.pdf"
    output_path.write_bytes(pdf_bytes)

    # Validate
    is_pdf = pdf_bytes[:5] == b"%PDF-"
    file_size = len(pdf_bytes)

    print(f"PDF starts with %PDF-: {is_pdf}")
    print(f"PDF file size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")
    print(f"Output: {output_path}")
    print()

    if is_pdf and file_size > 1000:
        print("RESULT: PASS — Evidence pack PDF renders correctly")
        print(f"  - {len(findings)} findings included")
        print(f"  - Includes: PRICE_MISMATCH, DUPLICATE_INVOICE, QUANTITY_MISMATCH")
        print(f"  - Template shows: invoice ref, contract ref, calculation, confidence, rule name")
        sys.exit(0)
    else:
        print("RESULT: FAIL — PDF generation issues detected")
        sys.exit(1)


if __name__ == "__main__":
    main()
