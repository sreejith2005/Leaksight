"""
Tests for normalization_service.py — Step 4.10

Source: docs/ARCHITECTURE.md (Section 6.3 — normalization_service.py)
       docs/PARSING_SPEC.md (Section 8 — confidence enforcement)
       docs/DATABASE_SCHEMA.md (Sections 3.3, 3.11, 3.12)

Covers:
  - Total failure skip (confidence == 0)
  - Missing vendor name skip
  - Vendor resolution via match_vendor (GST, ALIAS, FUZZY)
  - Auto-create vendor on NO_MATCH
  - Invoice creation with header fields
  - Line item creation with item normalization
  - Vendor raw_names_jsonb update (dedup)
  - Safe decimal conversion edge cases
  - Non-invoice doc type (no invoice/line items created)
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from backend.app.matching.vendor_matcher import MatchMethod, VendorMatchResult
from backend.app.models.contracts import ContractLineItem
from backend.app.models.invoices import Invoice, InvoiceLineItem
from backend.app.parsers.base_parser import (
    DocType,
    DocumentHeader,
    LineItem,
    ParseResult,
)
from backend.app.services.normalization_service import (
    NormalizationResult,
    _delete_existing_canonical_for_document,
    _auto_create_vendor,
    _create_invoice,
    _create_line_items,
    _process_contract_batch,
    _process_invoice_batch,
    _safe_decimal,
    _update_vendor_raw_names,
    normalize_parse_result,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TENANT_ID = uuid4()
DOC_ID = uuid4()
VENDOR_ID = uuid4()
INVOICE_ID = uuid4()


def _make_parse_result(
    confidence: float = 0.85,
    vendor_name: str = "Acme Pvt Ltd",
    gst_id: str | None = "22AAAAA0000A1Z5",
    doc_number: str = "INV-001",
    doc_date: date | None = date(2024, 1, 15),
    total_amount: Decimal | None = Decimal("5000.00"),
    currency: str = "INR",
    doc_type: DocType = DocType.INVOICE,
    line_items: list[LineItem] | None = None,
) -> ParseResult:
    """Helper to build a ParseResult for testing."""
    if line_items is None:
        line_items = [
            LineItem(
                line_number=1,
                item_desc="Steel Rebar 12mm TMT",
                quantity=Decimal("100"),
                unit="MT",
                unit_price=Decimal("45.00"),
                line_total=Decimal("4500.00"),
            ),
            LineItem(
                line_number=2,
                item_desc="Cement OPC 53 Grade",
                quantity=Decimal("50"),
                unit="BAG",
                unit_price=Decimal("10.00"),
                line_total=Decimal("500.00"),
            ),
        ]

    return ParseResult(
        document_id=DOC_ID,
        doc_type=doc_type,
        parser_used="ExcelParser",
        parser_version="1.0.0",
        parse_confidence=confidence,
        header=DocumentHeader(
            vendor_name=vendor_name,
            vendor_gst_id=gst_id,
            document_number=doc_number,
            document_date=doc_date,
            total_amount=total_amount,
            currency=currency,
        ),
        line_items=line_items,
    )


def _mock_db() -> AsyncMock:
    """Create a mock async DB session."""
    db = AsyncMock()
    db.add = MagicMock()  # synchronous method
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


# ===========================================================================
# Test: Total failure skip
# ===========================================================================


class TestTotalFailureSkip:
    """When parse_confidence == 0, normalization must be skipped entirely."""

    @pytest.mark.asyncio
    async def test_skip_on_zero_confidence(self):
        db = _mock_db()
        pr = _make_parse_result(confidence=0.0)

        result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.skipped is True
        assert result.skip_reason == "total_parse_failure"
        assert result.vendor_id is None
        assert result.invoice_id is None
        assert result.line_items_created == 0

    @pytest.mark.asyncio
    async def test_skip_does_not_call_match_vendor(self):
        db = _mock_db()
        pr = _make_parse_result(confidence=0.0)

        with patch(
            "backend.app.services.normalization_service.match_vendor"
        ) as mock_match:
            await normalize_parse_result(db, pr, TENANT_ID)
            mock_match.assert_not_called()


# ===========================================================================
# Test: Missing vendor name skip
# ===========================================================================


class TestMissingVendorSkip:
    """When vendor_name is None or empty, normalization must be skipped."""

    @pytest.mark.asyncio
    async def test_skip_on_none_vendor(self):
        db = _mock_db()
        pr = _make_parse_result(vendor_name=None)

        # vendor_name is set via header, but we need to set it to None
        pr.header.vendor_name = None

        result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.skipped is True
        assert result.skip_reason == "missing_vendor_name"

    @pytest.mark.asyncio
    async def test_skip_on_empty_string_vendor(self):
        db = _mock_db()
        pr = _make_parse_result(vendor_name="")

        pr.header.vendor_name = ""

        result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.skipped is True
        assert result.skip_reason == "missing_vendor_name"

    @pytest.mark.asyncio
    async def test_skip_on_whitespace_only_vendor(self):
        db = _mock_db()
        pr = _make_parse_result(vendor_name="   ")

        pr.header.vendor_name = "   "

        result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.skipped is True
        assert result.skip_reason == "missing_vendor_name"


# ===========================================================================
# Test: Vendor resolution — matched case
# ===========================================================================


class TestVendorResolutionMatched:
    """When match_vendor returns a matched vendor, use it directly."""

    @pytest.mark.asyncio
    async def test_gst_match_uses_existing_vendor(self):
        db = _mock_db()
        pr = _make_parse_result()

        match_result = VendorMatchResult(
            matched_vendor_id=VENDOR_ID,
            confidence=1.0,
            match_method=MatchMethod.GST_EXACT,
            needs_manual_review=False,
        )

        # Mock vendor raw_names query
        raw_names_mock = MagicMock()
        raw_names_mock.scalar_one_or_none.return_value = ["Some Old Name"]
        db.execute.return_value = raw_names_mock

        with (
            patch(
                "backend.app.services.normalization_service.match_vendor",
                return_value=match_result,
            ),
            patch(
                "backend.app.services.normalization_service.create_item_normalizer",
            ) as mock_normalizer_factory,
        ):
            mock_normalizer = MagicMock()
            mock_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()
            mock_normalizer_factory.return_value = mock_normalizer

            result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.vendor_id == VENDOR_ID
        assert result.vendor_match_method == "GST_EXACT"
        assert result.vendor_match_confidence == 1.0
        assert result.skipped is False

    @pytest.mark.asyncio
    async def test_fuzzy_match_uses_existing_vendor(self):
        db = _mock_db()
        pr = _make_parse_result()

        match_result = VendorMatchResult(
            matched_vendor_id=VENDOR_ID,
            confidence=0.92,
            match_method=MatchMethod.FUZZY,
            needs_manual_review=False,
        )

        raw_names_mock = MagicMock()
        raw_names_mock.scalar_one_or_none.return_value = ["Acme Ltd"]
        db.execute.return_value = raw_names_mock

        with (
            patch(
                "backend.app.services.normalization_service.match_vendor",
                return_value=match_result,
            ),
            patch(
                "backend.app.services.normalization_service.create_item_normalizer",
            ) as mock_normalizer_factory,
        ):
            mock_normalizer = MagicMock()
            mock_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()
            mock_normalizer_factory.return_value = mock_normalizer

            result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.vendor_id == VENDOR_ID
        assert result.vendor_match_method == "FUZZY"
        assert result.vendor_match_confidence == 0.92


# ===========================================================================
# Test: Vendor auto-creation on NO_MATCH
# ===========================================================================


class TestVendorAutoCreation:
    """When match_vendor returns NO_MATCH, a new vendor must be auto-created."""

    @pytest.mark.asyncio
    async def test_auto_create_vendor_on_no_match(self):
        db = _mock_db()
        pr = _make_parse_result()

        match_result = VendorMatchResult(
            matched_vendor_id=None,
            confidence=0.0,
            match_method=MatchMethod.NO_MATCH,
            needs_manual_review=True,
        )

        with (
            patch(
                "backend.app.services.normalization_service.match_vendor",
                return_value=match_result,
            ),
            patch(
                "backend.app.services.normalization_service._auto_create_vendor",
                return_value=VENDOR_ID,
            ) as mock_create,
            patch(
                "backend.app.services.normalization_service.create_item_normalizer",
            ) as mock_normalizer_factory,
        ):
            mock_normalizer = MagicMock()
            mock_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()
            mock_normalizer_factory.return_value = mock_normalizer

            result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.vendor_match_method == "AUTO_CREATED"
        assert result.vendor_id == VENDOR_ID
        mock_create.assert_awaited_once_with(
            db=db,
            raw_name="Acme Pvt Ltd",
            gst_id="22AAAAA0000A1Z5",
            tenant_id=TENANT_ID,
        )

    @pytest.mark.asyncio
    async def test_auto_create_vendor_db_write(self):
        """Directly test _auto_create_vendor writes to DB."""
        db = _mock_db()

        # After flush, vendor.id should be populated
        # We need to make db.add capture the vendor so we can check it
        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        with patch(
            "backend.app.services.normalization_service.normalize_vendor_name",
            return_value="acme",
        ):
            await _auto_create_vendor(
                db=db,
                raw_name="Acme Pvt Ltd",
                gst_id="22AAAAA0000A1Z5",
                tenant_id=TENANT_ID,
            )

        assert len(added_objects) == 1
        vendor = added_objects[0]
        assert vendor.normalized_name == "acme"
        assert vendor.raw_names_jsonb == ["Acme Pvt Ltd"]
        assert vendor.gst_id == "22AAAAA0000A1Z5"
        assert vendor.tenant_id == TENANT_ID
        db.flush.assert_awaited_once()


# ===========================================================================
# Test: Invoice creation
# ===========================================================================


class TestInvoiceCreation:
    """Verify canonical Invoice row is created with correct fields."""

    @pytest.mark.asyncio
    async def test_invoice_created_with_header_fields(self):
        db = _mock_db()
        pr = _make_parse_result()

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        await _create_invoice(db, pr, VENDOR_ID, TENANT_ID)

        invoices = [o for o in added_objects if isinstance(o, Invoice)]
        assert len(invoices) == 1
        inv = invoices[0]
        assert inv.tenant_id == TENANT_ID
        assert inv.vendor_id == VENDOR_ID
        assert inv.invoice_no == "INV-001"
        assert inv.invoice_date == date(2024, 1, 15)
        assert inv.total_amount == Decimal("5000.00")
        assert inv.currency == "INR"
        assert inv.source_document_id == DOC_ID
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invoice_fallbacks_for_missing_fields(self):
        """Missing date/amount/currency should use safe fallbacks."""
        db = _mock_db()
        pr = _make_parse_result(
            doc_number=None,
            doc_date=None,
            total_amount=None,
            currency=None,
        )

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        await _create_invoice(db, pr, VENDOR_ID, TENANT_ID)

        invoices = [o for o in added_objects if isinstance(o, Invoice)]
        inv = invoices[0]
        assert inv.invoice_no == ""
        assert inv.invoice_date == date.today()
        assert inv.total_amount == Decimal("0")
        assert inv.currency == "INR"


# ===========================================================================
# Test: Line item creation with normalization
# ===========================================================================


class TestLineItemCreation:
    """Verify InvoiceLineItem rows are created with normalized descriptions."""

    @pytest.mark.asyncio
    async def test_line_items_created(self):
        db = _mock_db()
        pr = _make_parse_result()

        mock_normalizer = MagicMock()
        mock_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        count = await _create_line_items(
            db, pr, INVOICE_ID, TENANT_ID, mock_normalizer
        )

        assert count == 2
        line_items = [o for o in added_objects if isinstance(o, InvoiceLineItem)]
        assert len(line_items) == 2

        # First line item
        li1 = line_items[0]
        assert li1.invoice_id == INVOICE_ID
        assert li1.tenant_id == TENANT_ID
        assert li1.raw_item_desc == "Steel Rebar 12mm TMT"
        assert li1.item_desc == "steel rebar 12mm tmt"  # normalized
        assert li1.quantity == Decimal("100")
        assert li1.unit == "MT"
        assert li1.unit_price == Decimal("45.00")
        assert li1.line_total == Decimal("4500.00")

        # Second line item
        li2 = line_items[1]
        assert li2.raw_item_desc == "Cement OPC 53 Grade"
        assert li2.item_desc == "cement opc 53 grade"

    @pytest.mark.asyncio
    async def test_line_items_with_missing_values(self):
        """Missing quantity/price should default to Decimal('0')."""
        db = _mock_db()
        pr = _make_parse_result(
            line_items=[
                LineItem(
                    line_number=1,
                    item_desc=None,
                    quantity=None,
                    unit=None,
                    unit_price=None,
                    line_total=None,
                ),
            ]
        )

        mock_normalizer = MagicMock()
        mock_normalizer.normalize_item_desc.return_value = ""

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        count = await _create_line_items(
            db, pr, INVOICE_ID, TENANT_ID, mock_normalizer
        )

        assert count == 1
        li = [o for o in added_objects if isinstance(o, InvoiceLineItem)][0]
        assert li.raw_item_desc == ""
        assert li.item_desc == ""
        assert li.quantity == Decimal("0")
        assert li.unit == ""
        assert li.unit_price == Decimal("0")
        assert li.line_total == Decimal("0")  # 0 * 0 = 0

    @pytest.mark.asyncio
    async def test_empty_line_items_list(self):
        """Zero line items should return count 0."""
        db = _mock_db()
        pr = _make_parse_result(line_items=[])
        mock_normalizer = MagicMock()

        count = await _create_line_items(
            db, pr, INVOICE_ID, TENANT_ID, mock_normalizer
        )

        assert count == 0
        db.flush.assert_awaited_once()


# ===========================================================================
# Test: Vendor raw_names_jsonb update
# ===========================================================================


class TestVendorRawNamesUpdate:
    """Verify raw_names_jsonb is updated with deduplication."""

    @pytest.mark.asyncio
    async def test_new_name_appended(self):
        db = _mock_db()

        raw_names_mock = MagicMock()
        raw_names_mock.scalar_one_or_none.return_value = ["Old Name"]
        db.execute.return_value = raw_names_mock

        await _update_vendor_raw_names(db, VENDOR_ID, "New Name")

        # Second call should be the UPDATE statement
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_duplicate_name_not_appended(self):
        db = _mock_db()

        raw_names_mock = MagicMock()
        raw_names_mock.scalar_one_or_none.return_value = ["Acme Pvt Ltd"]
        db.execute.return_value = raw_names_mock

        await _update_vendor_raw_names(db, VENDOR_ID, "Acme Pvt Ltd")

        # Only the SELECT call — no UPDATE because name already exists
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_none_raw_names_treated_as_empty(self):
        db = _mock_db()

        raw_names_mock = MagicMock()
        raw_names_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = raw_names_mock

        await _update_vendor_raw_names(db, VENDOR_ID, "First Name")

        # SELECT + UPDATE
        assert db.execute.await_count == 2


# ===========================================================================
# Test: Safe decimal conversion
# ===========================================================================


class TestSafeDecimal:
    """Edge cases for _safe_decimal helper."""

    def test_none_returns_default(self):
        assert _safe_decimal(None, Decimal("99")) == Decimal("99")

    def test_valid_decimal(self):
        assert _safe_decimal(Decimal("42.5"), Decimal("0")) == Decimal("42.5")

    def test_invalid_string_returns_default(self):
        assert _safe_decimal("not_a_number", Decimal("0")) == Decimal("0")

    def test_integer_converted(self):
        assert _safe_decimal(10, Decimal("0")) == Decimal("10")


# ===========================================================================
# Test: Non-invoice doc type (no invoice/line items)
# ===========================================================================


class TestNonInvoiceDocType:
    """For non-INVOICE doc types, vendor is resolved but no invoice/items created."""

    @pytest.mark.asyncio
    async def test_po_doc_type_no_invoice_created(self):
        db = _mock_db()
        pr = _make_parse_result(doc_type=DocType.PO)

        match_result = VendorMatchResult(
            matched_vendor_id=VENDOR_ID,
            confidence=1.0,
            match_method=MatchMethod.GST_EXACT,
            needs_manual_review=False,
        )

        raw_names_mock = MagicMock()
        raw_names_mock.scalar_one_or_none.return_value = []
        db.execute.return_value = raw_names_mock

        with patch(
            "backend.app.services.normalization_service.match_vendor",
            return_value=match_result,
        ):
            result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.vendor_id == VENDOR_ID
        assert result.invoice_id is None
        assert result.line_items_created == 0
        assert result.skipped is False


# ===========================================================================
# Test: Full pipeline integration (mocked)
# ===========================================================================


class TestFullPipelineIntegration:
    """End-to-end normalization pipeline with all steps mocked."""

    @pytest.mark.asyncio
    async def test_full_pipeline_gst_match(self):
        """Full pipeline: GST match → invoice → 2 line items."""
        db = _mock_db()
        pr = _make_parse_result()

        match_result = VendorMatchResult(
            matched_vendor_id=VENDOR_ID,
            confidence=1.0,
            match_method=MatchMethod.GST_EXACT,
            needs_manual_review=False,
        )

        # Mock for _update_vendor_raw_names SELECT
        raw_names_mock = MagicMock()
        raw_names_mock.scalar_one_or_none.return_value = []
        db.execute.return_value = raw_names_mock

        added_objects = []

        def _add_with_id(obj):
            """Simulate DB setting id on flush for Invoice objects."""
            if isinstance(obj, Invoice) and obj.id is None:
                obj.id = INVOICE_ID
            added_objects.append(obj)

        db.add.side_effect = _add_with_id

        with (
            patch(
                "backend.app.services.normalization_service.match_vendor",
                return_value=match_result,
            ),
            patch(
                "backend.app.services.normalization_service.create_item_normalizer",
            ) as mock_normalizer_factory,
        ):
            mock_normalizer = MagicMock()
            mock_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()
            mock_normalizer_factory.return_value = mock_normalizer

            result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.skipped is False
        assert result.vendor_id == VENDOR_ID
        assert result.vendor_match_method == "GST_EXACT"
        assert result.vendor_match_confidence == 1.0
        assert result.invoice_id == INVOICE_ID
        assert result.line_items_created == 2

        # Should have created 1 invoice + 2 line items
        invoices = [o for o in added_objects if isinstance(o, Invoice)]
        line_items = [o for o in added_objects if isinstance(o, InvoiceLineItem)]
        assert len(invoices) == 1
        assert len(line_items) == 2

    @pytest.mark.asyncio
    async def test_full_pipeline_no_match_auto_creates(self):
        """Full pipeline: NO_MATCH → auto-create vendor → invoice → line items."""
        db = _mock_db()
        pr = _make_parse_result()

        match_result = VendorMatchResult(
            matched_vendor_id=None,
            confidence=0.0,
            match_method=MatchMethod.NO_MATCH,
            needs_manual_review=True,
        )

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        with (
            patch(
                "backend.app.services.normalization_service.match_vendor",
                return_value=match_result,
            ),
            patch(
                "backend.app.services.normalization_service._auto_create_vendor",
                return_value=VENDOR_ID,
            ),
            patch(
                "backend.app.services.normalization_service.create_item_normalizer",
            ) as mock_normalizer_factory,
        ):
            mock_normalizer = MagicMock()
            mock_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()
            mock_normalizer_factory.return_value = mock_normalizer

            result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.vendor_match_method == "AUTO_CREATED"
        assert result.vendor_id == VENDOR_ID
        assert result.line_items_created == 2


class TestBatchInvoiceNormalization:
    """Batch invoice path should tolerate duplicate invoice_no rows."""

    @pytest.mark.asyncio
    async def test_duplicate_invoice_no_reuses_existing_invoice(self):
        db = _mock_db()

        existing_invoice = Invoice(
            id=INVOICE_ID,
            tenant_id=TENANT_ID,
            vendor_id=uuid4(),
            invoice_no="INV-DUP-001",
            invoice_date=date(2024, 1, 1),
            total_amount=Decimal("1"),
            currency="INR",
            source_document_id=uuid4(),
        )

        # execute() calls in _process_invoice_batch:
        # 1) existing invoice lookup by tenant_id + invoice_no
        # 2) existing line-item count for that invoice
        existing_lookup = MagicMock()
        existing_lookup.scalar_one_or_none.return_value = existing_invoice
        li_count_result = MagicMock()
        li_count_result.scalar.return_value = 1
        db.execute.side_effect = [existing_lookup, li_count_result]

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        batch_rows = [
            {
                "invoice_no": "INV-DUP-001",
                "invoice_date": "2024-01-15",
                "vendor_name": "Acme Pvt Ltd",
                "currency": "USD",
                "item_desc": "Cloud Hosting",
                "quantity": 2,
                "unit": "Month",
                "unit_price": 100,
            }
        ]

        mock_item_normalizer = MagicMock()
        mock_item_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()

        with patch(
            "backend.app.services.normalization_service._resolve_or_create_vendor",
            new_callable=AsyncMock,
            return_value=VENDOR_ID,
        ):
            invoices_created, line_items_created = await _process_invoice_batch(
                db=db,
                batch_rows=batch_rows,
                tenant_id=TENANT_ID,
                item_normalizer=mock_item_normalizer,
                document_id=DOC_ID,
            )

        assert invoices_created == 1
        assert line_items_created == 0

        # Existing invoice reused and relinked to current document
        assert existing_invoice.source_document_id == DOC_ID

        # No new invoice object should be added
        assert len([o for o in added_objects if isinstance(o, Invoice)]) == 0
        assert len([o for o in added_objects if isinstance(o, InvoiceLineItem)]) == 0

    @pytest.mark.asyncio
    async def test_batch_invoice_stores_contract_ref_on_line_items(self):
        db = _mock_db()
        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)
        existing_lookup = MagicMock()
        existing_lookup.scalar_one_or_none.return_value = None
        db.execute.side_effect = [existing_lookup]

        batch_rows = [
            {
                "invoice_no": "INV-REF-001",
                "contract_id": "CTR-001",
                "invoice_date": "2024-01-15",
                "vendor_name": "Acme Pvt Ltd",
                "currency": "USD",
                "item_desc": "Cloud Hosting",
                "quantity": 2,
                "unit": "Month",
                "unit_price": 100,
            }
        ]

        mock_item_normalizer = MagicMock()
        mock_item_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()

        with patch(
            "backend.app.services.normalization_service._resolve_or_create_vendor",
            new_callable=AsyncMock,
            return_value=VENDOR_ID,
        ):
            _, line_items_created = await _process_invoice_batch(
                db=db,
                batch_rows=batch_rows,
                tenant_id=TENANT_ID,
                item_normalizer=mock_item_normalizer,
                document_id=DOC_ID,
            )

        assert line_items_created == 1
        line_items = [o for o in added_objects if isinstance(o, InvoiceLineItem)]
        assert len(line_items) == 1
        assert line_items[0].contract_ref == "CTR-001"


class TestBatchContractNormalization:
    @pytest.mark.asyncio
    async def test_batch_contract_stores_contract_quantity(self):
        db = _mock_db()
        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        batch_rows = [
            {
                "contract_id": "CTR-001",
                "vendor_name": "Acme Pvt Ltd",
                "effective_start_date": "2024-01-01",
                "effective_end_date": "2024-12-31",
                "item_desc": "Cloud Hosting",
                "quantity": 24,
                "unit": "Month",
                "unit_price": 100,
                "currency": "USD",
            }
        ]

        mock_item_normalizer = MagicMock()
        mock_item_normalizer.normalize_item_desc.side_effect = lambda x: x.lower()

        with patch(
            "backend.app.services.normalization_service._resolve_or_create_vendor",
            new_callable=AsyncMock,
            return_value=VENDOR_ID,
        ):
            _, line_items_created = await _process_contract_batch(
                db=db,
                batch_rows=batch_rows,
                tenant_id=TENANT_ID,
                item_normalizer=mock_item_normalizer,
                document_id=DOC_ID,
            )

        assert line_items_created == 1
        line_items = [o for o in added_objects if isinstance(o, ContractLineItem)]
        assert len(line_items) == 1
        assert line_items[0].contract_quantity == Decimal("24")


class TestDocumentScopedCleanup:
    """Normalization must clear stale canonical rows for the source document."""

    @pytest.mark.asyncio
    async def test_batch_contract_cleanup_runs_before_insert(self):
        db = _mock_db()
        pr = ParseResult(
            document_id=DOC_ID,
            doc_type=DocType.CONTRACT,
            parser_used="ExcelParser",
            parser_version="1.0.0",
            parse_confidence=0.95,
            header=DocumentHeader(vendor_name="Acme Pvt Ltd"),
            line_items=[],
            raw_extracted_data={
                "batch_type": "CONTRACT",
                "batch_rows": [
                    {
                        "contract_id": "CTR-001",
                        "vendor_name": "Acme Pvt Ltd",
                        "item_desc": "Cloud Hosting",
                        "unit": "Month",
                        "unit_price": 100,
                        "currency": "INR",
                    }
                ],
            },
        )

        call_order: list[str] = []

        async def cleanup_side_effect(*args, **kwargs):
            call_order.append("cleanup")

        async def process_side_effect(*args, **kwargs):
            call_order.append("process")
            return (1, 1)

        with (
            patch(
                "backend.app.services.normalization_service._delete_existing_canonical_for_document",
                new=AsyncMock(side_effect=cleanup_side_effect),
            ) as mock_cleanup,
            patch(
                "backend.app.services.normalization_service.create_item_normalizer",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "backend.app.services.normalization_service._process_contract_batch",
                new=AsyncMock(side_effect=process_side_effect),
            ) as mock_process,
        ):
            result = await normalize_parse_result(db, pr, TENANT_ID)

        assert result.contracts_created == 1
        assert result.line_items_created == 1
        assert call_order == ["cleanup", "process"]
        mock_cleanup.assert_awaited_once_with(
            db=db,
            tenant_id=TENANT_ID,
            document_id=DOC_ID,
            doc_type=DocType.CONTRACT,
        )
        mock_process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_contract_cleanup_deletes_headers_versions_and_lines(self):
        db = _mock_db()

        await _delete_existing_canonical_for_document(
            db=db,
            tenant_id=TENANT_ID,
            document_id=DOC_ID,
            doc_type=DocType.CONTRACT,
        )

        assert db.execute.await_count == 3
        statements = [str(call.args[0]) for call in db.execute.await_args_list]
        assert "DELETE FROM contract_line_items" in statements[0]
        assert "DELETE FROM contract_versions" in statements[1]
        assert "DELETE FROM contracts" in statements[2]
