"""Celery tasks for Tool A contract structuring."""

from __future__ import annotations

from datetime import date
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import func, select

from backend.app.core.celery_app import celery_app
from backend.app.core.celery_async import run_async as _run_async
from backend.app.core.config import get_settings
from backend.app.core.database import async_session_factory
from backend.app.core.logging import get_logger
from backend.app.core.tenant_context import set_tenant_context
from backend.app.matching.vendor_normalizer import normalize_vendor_name
from backend.app.models.contracts import Contract, ContractLineItem, ContractVersion
from backend.app.models.raw import Document
from backend.app.models.vendors import Vendor
from backend.app.tools.contract_structuring.extractors import structure_contract
from backend.app.tools.contract_structuring.exporters.erp_json_exporter import (
    export_erp_csv,
    export_erp_json,
)
from backend.app.tools.contract_structuring.exporters.excel_exporter import export_structuring_excel
from backend.app.tools.contract_structuring.extractors.clause_extractor import ClauseExtractor
from backend.app.tools.contract_structuring.extractors.docx_extractor import DocxExtractor
from backend.app.tools.contract_structuring.extractors.excel_extractor import ExcelExtractor
from backend.app.tools.contract_structuring.extractors.multi_page_stitcher import MultiPageStitcher
from backend.app.tools.contract_structuring.extractors.pdf_extractor import PdfExtractor
from backend.app.tools.contract_structuring.extractors.table_normalizer import TableNormalizer
from backend.app.tools.contract_structuring.extractors.version_detector import VersionDetector
from backend.app.tools.contract_structuring.models import (
    ContractStructuringExport,
    ContractStructuringRun,
    ContractStructuringRunDocument,
    ExtractedClause,
    ExtractedLineItem,
    RawContractTable,
)

logger = get_logger(__name__)

DEFAULT_VALID_TO = date(2099, 12, 31)


def _format_task_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _extract_raw_tables(file_path: Path) -> list:
    extractor = _pick_extractor(file_path)
    result = extractor.extract(str(file_path))
    return list(getattr(result, "tables", []) or [])


def _pick_raw_table_for_line_item(raw_rows: list[RawContractTable], source_page: int | None) -> UUID | None:
    if not raw_rows:
        return None
    if source_page is None:
        return raw_rows[0].id

    for raw_row in raw_rows:
        if raw_row.source_page == source_page:
            return raw_row.id

    return raw_rows[0].id


def _pick_extractor(path: Path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        return PdfExtractor()
    if ext == ".docx":
        return DocxExtractor()
    if ext in {".xlsx", ".xls", ".csv"}:
        return ExcelExtractor()
    raise ValueError(f"Unsupported document format for structuring: {ext}")


async def _structure_single_contract_async(
    document_id: UUID,
    run_document_id: UUID,
    tenant_id: UUID,
    *,
    final_failure: bool,
) -> dict:
    started = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_id)

        run_doc = await db.scalar(
            select(ContractStructuringRunDocument).where(
                ContractStructuringRunDocument.id == run_document_id,
                ContractStructuringRunDocument.tenant_id == tenant_id,
            )
        )
        if run_doc is None:
            raise LookupError(f"RunDocumentNotFound:{run_document_id}")

        run_doc.task_status = "PROCESSING"
        run_doc.error_message = None
        run = await db.scalar(
            select(ContractStructuringRun).where(
                ContractStructuringRun.id == run_doc.run_id,
                ContractStructuringRun.tenant_id == tenant_id,
            )
        )
        if run is not None:
            run.status = "PROCESSING"
            if run.started_at is None:
                run.started_at = started
        await db.flush()

        try:
            doc = await db.scalar(
                select(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
            )
            if doc is None:
                raise ValueError("DocumentNotFound")

            settings = get_settings()
            file_path = Path(settings.document_storage_path) / doc.file_path
            if not file_path.exists():
                raise FileNotFoundError(f"Document file not found: {file_path}")

            # Ensure file type is read from document metadata for auditability.
            logger.info(
                "tool_a_structuring_document_loaded",
                document_id=str(document_id),
                run_document_id=str(run_document_id),
                tenant_id=str(tenant_id),
                doc_type=str(doc.doc_type),
                file_path=str(file_path),
            )

            raw_tables = _extract_raw_tables(file_path)
            persisted_raw_rows: list[RawContractTable] = []
            for table in raw_tables:
                raw_row = RawContractTable(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    run_document_id=run_document_id,
                    source_page=table.source_page,
                    extraction_method=table.extraction_method,
                    raw_table_json=table.raw_table_json,
                    table_confidence=table.table_confidence,
                    column_count=table.column_count,
                    row_count=table.row_count,
                    is_continuation=False,
                    continued_from_id=None,
                )
                db.add(raw_row)
                await db.flush()
                persisted_raw_rows.append(raw_row)

            for idx, table in enumerate(raw_tables):
                if not table.is_continuation:
                    continue
                current_row = persisted_raw_rows[idx]
                if table.continued_from_index is None:
                    continue
                if table.continued_from_index < 0 or table.continued_from_index >= len(persisted_raw_rows):
                    continue
                current_row.is_continuation = True
                current_row.continued_from_id = persisted_raw_rows[table.continued_from_index].id

            line_items, clause_results, version_number, _ = structure_contract(
                document_path=str(file_path),
                tenant_id=str(tenant_id),
                db_session=db,
            )

            for item in line_items:
                raw_table_id = _pick_raw_table_for_line_item(
                    persisted_raw_rows,
                    item.source_page,
                )
                if raw_table_id is None:
                    continue
                li = ExtractedLineItem(
                    tenant_id=tenant_id,
                    run_id=run_doc.run_id,
                    document_id=document_id,
                    raw_table_id=raw_table_id,
                    contract_id=item.contract_id,
                    item_description=item.item_description,
                    unit_raw=item.unit_raw,
                    unit_price=item.unit_price,
                    currency=item.currency,
                    effective_date=_parse_iso_date(item.effective_date),
                    expiry_date=_parse_iso_date(item.expiry_date),
                    version_number=item.version_number or version_number or 1,
                    source_page=item.source_page,
                    item_confidence=item.item_confidence,
                    price_confidence=item.price_confidence,
                    unit_confidence=item.unit_confidence,
                    review_status="PENDING_REVIEW",
                    needs_review=item.needs_review
                    or item.item_description is None
                    or item.unit_price is None,
                )
                db.add(li)

            for clause in clause_results:
                c = ExtractedClause(
                    tenant_id=tenant_id,
                    run_id=run_doc.run_id,
                    document_id=document_id,
                    clause_type=clause.clause_type,
                    raw_text=clause.raw_text,
                    extracted_value=clause.extracted_value,
                    source_page=clause.source_page,
                    confidence=clause.confidence,
                    needs_review=clause.needs_review or clause.confidence < 0.7,
                    review_status="PENDING_REVIEW",
                )
                db.add(c)

            run_doc.task_status = "COMPLETE"
            run_doc.processing_time_seconds = (
                datetime.now(timezone.utc) - started
            ).total_seconds()
            await db.commit()

            await _update_structuring_run_status_async(run_doc.run_id, tenant_id)

            return {
                "status": "success",
                "run_document_id": str(run_document_id),
                "document_id": str(document_id),
            }

        except Exception as exc:
            await db.rollback()
            await set_tenant_context(db, tenant_id)
            run_doc = await db.scalar(
                select(ContractStructuringRunDocument).where(
                    ContractStructuringRunDocument.id == run_document_id,
                    ContractStructuringRunDocument.tenant_id == tenant_id,
                )
            )
            if run_doc is not None:
                if final_failure:
                    run_doc.task_status = "FAILED"
                    run_doc.error_message = _format_task_error(exc)
                    run_doc.processing_time_seconds = (
                        datetime.now(timezone.utc) - started
                    ).total_seconds()
                else:
                    # Keep the document non-terminal while Celery schedules a retry.
                    run_doc.task_status = "PROCESSING"
                    run_doc.error_message = None
                    run_doc.processing_time_seconds = None
                await db.commit()
                await _update_structuring_run_status_async(run_doc.run_id, tenant_id)

            raise


async def _update_structuring_run_status_async(run_id: UUID, tenant_id: UUID) -> dict:
    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_id)
        run = await db.scalar(
            select(ContractStructuringRun).where(
                ContractStructuringRun.id == run_id,
                ContractStructuringRun.tenant_id == tenant_id,
            )
        )
        if run is None:
            return {"status": "failed", "error": "RunNotFound", "run_id": str(run_id)}

        statuses = list(
            (
                await db.execute(
                    select(ContractStructuringRunDocument.task_status).where(
                        ContractStructuringRunDocument.run_id == run_id,
                        ContractStructuringRunDocument.tenant_id == tenant_id,
                    )
                )
            ).scalars()
        )

        run.total_documents = len(statuses)
        run.processed_documents = sum(1 for s in statuses if s in {"COMPLETE", "FAILED"})

        if statuses and all(s == "COMPLETE" for s in statuses):
            run.status = "COMPLETE"
        elif statuses and any(s == "COMPLETE" for s in statuses) and any(s == "FAILED" for s in statuses):
            run.status = "PARTIAL_SUCCESS"
        elif statuses and all(s == "FAILED" for s in statuses):
            run.status = "FAILED"
        elif statuses and any(s in {"PROCESSING", "COMPLETE", "FAILED"} for s in statuses):
            run.status = "PROCESSING"
        else:
            run.status = "PENDING"

        if run.status in {"COMPLETE", "PARTIAL_SUCCESS", "FAILED"}:
            if run.completed_at is None:
                run.completed_at = datetime.now(timezone.utc)
        else:
            run.completed_at = None
        if run.status in {"PROCESSING", "COMPLETE", "PARTIAL_SUCCESS", "FAILED"} and run.started_at is None:
            run.started_at = datetime.now(timezone.utc)

        run.total_line_items_found = (
            await db.execute(
                select(func.count()).select_from(ExtractedLineItem).where(
                    ExtractedLineItem.run_id == run_id,
                    ExtractedLineItem.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        run.total_clauses_found = (
            await db.execute(
                select(func.count()).select_from(ExtractedClause).where(
                    ExtractedClause.run_id == run_id,
                    ExtractedClause.tenant_id == tenant_id,
                )
            )
        ).scalar_one()

        await db.commit()
        return {
            "status": "success",
            "run_id": str(run_id),
            "run_status": run.status,
        }


def _build_export_payload(line_items: list[ExtractedLineItem], clauses: list[ExtractedClause]) -> tuple[list[dict], list[dict], list[dict]]:
    by_doc: dict[UUID, dict] = {}

    clause_map: dict[UUID, dict[str, str]] = {}
    for c in clauses:
        clause_map.setdefault(c.document_id, {})[c.clause_type] = c.extracted_value or ""

    csv_rows: list[dict] = []
    for item in line_items:
        doc_meta = clause_map.get(item.document_id, {})
        vendor_name = doc_meta.get("VENDOR_NAME") or ""
        contract_ref = doc_meta.get("CONTRACT_REF") or None
        effective_date = item.effective_date.isoformat() if item.effective_date else None
        expiry_date = item.expiry_date.isoformat() if item.expiry_date else None
        confidence = min(item.item_confidence, item.price_confidence, item.unit_confidence)

        by_doc.setdefault(
            item.document_id,
            {
                "vendor_name": vendor_name,
                "contract_reference": contract_ref,
                "effective_date": effective_date,
                "expiry_date": expiry_date,
                "version": item.version_number or 1,
                "source_document": str(item.document_id),
                "line_items": [],
            },
        )
        by_doc[item.document_id]["line_items"].append(
            {
                "item_description": item.item_description,
                "unit": item.unit_raw,
                "unit_price": float(item.unit_price) if item.unit_price is not None else None,
                "currency": item.currency or None,
                "slab_info": item.slab_info,
                "source_page": item.source_page,
                "confidence": round(float(confidence), 2),
            }
        )

        csv_rows.append(
            {
                "vendor_name": vendor_name,
                "contract_reference": contract_ref,
                "effective_date": effective_date,
                "expiry_date": expiry_date,
                "version": item.version_number or 1,
                "source_document": str(item.document_id),
                "item_description": item.item_description,
                "unit": item.unit_raw,
                "unit_price": float(item.unit_price) if item.unit_price is not None else None,
                "currency": item.currency or None,
                "source_page": item.source_page,
                "confidence": round(float(confidence), 2),
            }
        )

    excel_docs: list[dict] = []
    for doc_id, payload in by_doc.items():
        rows = []
        for li in payload["line_items"]:
            rows.append(
                {
                    "vendor_name": payload["vendor_name"],
                    "contract_id": payload["contract_reference"],
                    "effective_date": None,
                    "expiry_date": None,
                    "item_description": li["item_description"],
                    "unit_raw": li["unit"],
                    "unit_price": li["unit_price"],
                    "currency": li["currency"],
                    "version_number": payload["version"],
                    "source_page": li["source_page"],
                    "confidence": li["confidence"],
                    "needs_review": False,
                }
            )
        excel_docs.append({"sheet_name": str(doc_id), "rows": rows})

    return excel_docs, list(by_doc.values()), csv_rows


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _resolve_validity_window(
    effective_dates: list[date | None],
    expiry_dates: list[date | None],
    clause_effective: str | None,
    clause_expiry: str | None,
) -> tuple[date, date]:
    valid_from_candidates = [d for d in effective_dates if d is not None]
    valid_to_candidates = [d for d in expiry_dates if d is not None]

    clause_effective_date = _parse_iso_date(clause_effective)
    clause_expiry_date = _parse_iso_date(clause_expiry)

    if clause_effective_date is not None:
        valid_from_candidates.append(clause_effective_date)
    if clause_expiry_date is not None:
        valid_to_candidates.append(clause_expiry_date)

    valid_from = min(valid_from_candidates) if valid_from_candidates else date.today()
    valid_to = max(valid_to_candidates) if valid_to_candidates else DEFAULT_VALID_TO

    if valid_to < valid_from:
        valid_to = valid_from

    return valid_from, valid_to


async def _resolve_vendor(
    db,
    tenant_id: UUID,
    raw_vendor_name: str,
) -> Vendor:
    normalized_vendor_name = normalize_vendor_name(raw_vendor_name)
    if not normalized_vendor_name:
        raise ValueError("MissingVendorName")

    vendor = await db.scalar(
        select(Vendor).where(
            Vendor.tenant_id == tenant_id,
            Vendor.normalized_name == normalized_vendor_name,
        )
    )
    if vendor is None:
        # Match existing vendors using the same normalized+fuzzy pattern used by core lookup.
        candidates = list(
            (
                await db.execute(
                    select(Vendor).where(
                        Vendor.tenant_id == tenant_id,
                    )
                )
            ).scalars()
        )
        best_vendor: Vendor | None = None
        best_score = 0.0
        for candidate in candidates:
            score = float(fuzz.token_sort_ratio(normalized_vendor_name, candidate.normalized_name))
            if score > best_score:
                best_score = score
                best_vendor = candidate

        if best_vendor is not None and best_score >= 85.0:
            vendor = best_vendor

    if vendor is None:
        vendor = Vendor(
            tenant_id=tenant_id,
            normalized_name=normalized_vendor_name,
            raw_names_jsonb=[raw_vendor_name],
        )
        db.add(vendor)
        await db.flush()
        return vendor

    raw_names = list(vendor.raw_names_jsonb or [])
    if raw_vendor_name not in raw_names:
        raw_names.append(raw_vendor_name)
        vendor.raw_names_jsonb = raw_names

    return vendor


async def _resolve_contract(
    db,
    tenant_id: UUID,
    vendor_id: UUID,
    contract_ref: str | None,
    source_document_id: UUID,
) -> Contract:
    contract_query = select(Contract).where(
        Contract.tenant_id == tenant_id,
        Contract.vendor_id == vendor_id,
    )
    if contract_ref:
        contract_query = contract_query.where(Contract.contract_ref == contract_ref)
    else:
        contract_query = contract_query.where(Contract.contract_ref.is_(None))

    contract = await db.scalar(contract_query.order_by(Contract.created_at.asc()).limit(1))
    if contract is not None:
        return contract

    contract = Contract(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        contract_ref=contract_ref,
        source_document_id=source_document_id,
    )
    db.add(contract)
    await db.flush()
    return contract


def _line_item_key(item_description: str, unit: str) -> tuple[str, str]:
    return (item_description.strip().lower(), unit.strip().lower())


async def _resolve_contract_version(
    db,
    contract_id: UUID,
    tenant_id: UUID,
    version_number: int,
    valid_from: date,
    valid_to: date,
) -> ContractVersion:
    contract_version = await db.scalar(
        select(ContractVersion).where(
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == tenant_id,
            ContractVersion.version_number == version_number,
        )
    )
    if contract_version is not None:
        contract_version.valid_from = min(contract_version.valid_from, valid_from)
        contract_version.valid_to = max(contract_version.valid_to, valid_to)
        return contract_version

    contract_version = ContractVersion(
        contract_id=contract_id,
        tenant_id=tenant_id,
        version_number=version_number,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    db.add(contract_version)
    await db.flush()
    return contract_version


async def _import_confirmed_items_to_leaksight(
    db,
    tenant_id: UUID,
    confirmed_items: list[ExtractedLineItem],
    clauses: list[ExtractedClause],
) -> dict[str, int]:
    clauses_by_document: dict[UUID, dict[str, str]] = {}
    for clause in clauses:
        clauses_by_document.setdefault(clause.document_id, {})[clause.clause_type] = (
            clause.extracted_value or ""
        )

    item_groups: dict[UUID, list[ExtractedLineItem]] = {}
    for item in confirmed_items:
        item_groups.setdefault(item.document_id, []).append(item)

    imported_contracts = 0
    imported_versions = 0
    imported_line_items = 0

    for document_id, doc_items in item_groups.items():
        doc_clauses = clauses_by_document.get(document_id, {})
        source_document = await db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        source_filename = (
            (source_document.original_filename if source_document is not None else None)
            or f"document-{document_id}"
        )

        vendor_name = doc_clauses.get("VENDOR_NAME", "").strip() or source_filename

        inferred_contract_id = next(
            (
                (item.contract_id or "").strip()
                for item in doc_items
                if (item.contract_id or "").strip()
            ),
            "",
        )
        contract_ref = (
            (doc_clauses.get("CONTRACT_REF") or "").strip()
            or inferred_contract_id
            or source_filename
        )
        version_number = max((item.version_number or 1) for item in doc_items)

        valid_from, valid_to = _resolve_validity_window(
            effective_dates=[item.effective_date for item in doc_items],
            expiry_dates=[item.expiry_date for item in doc_items],
            clause_effective=doc_clauses.get("EFFECTIVE_DATE"),
            clause_expiry=doc_clauses.get("EXPIRY_DATE"),
        )

        vendor = await _resolve_vendor(db, tenant_id, vendor_name)
        existing_contract = await db.scalar(
            select(Contract).where(
                Contract.tenant_id == tenant_id,
                Contract.vendor_id == vendor.id,
                Contract.contract_ref == contract_ref,
            )
        )
        contract = await _resolve_contract(db, tenant_id, vendor.id, contract_ref, document_id)

        existing_version = await db.scalar(
            select(ContractVersion).where(
                ContractVersion.contract_id == contract.id,
                ContractVersion.tenant_id == tenant_id,
                ContractVersion.version_number == version_number,
            )
        )
        contract_version = await _resolve_contract_version(
            db,
            contract.id,
            tenant_id,
            version_number,
            valid_from,
            valid_to,
        )

        if existing_contract is None:
            imported_contracts += 1
        if existing_version is None:
            imported_versions += 1

        existing_rows = list(
            (
                await db.execute(
                    select(ContractLineItem).where(
                        ContractLineItem.contract_version_id == contract_version.id,
                        ContractLineItem.tenant_id == tenant_id,
                    )
                )
            ).scalars()
        )
        existing_keys = {
            _line_item_key(row.item_desc, row.unit)
            for row in existing_rows
        }

        for item in doc_items:
            if item.item_description is None or item.unit_raw is None or item.unit_price is None:
                continue
            if not item.currency:
                logger.warning(
                    "tool_a_import_skipped_missing_currency",
                    tenant_id=str(tenant_id),
                    document_id=str(document_id),
                    item_description=item.item_description,
                )
                continue
            row_key = _line_item_key(item.item_description, item.unit_raw)
            if row_key in existing_keys:
                continue

            db.add(
                ContractLineItem(
                    contract_version_id=contract_version.id,
                    tenant_id=tenant_id,
                    item_desc=item.item_description.strip().lower(),
                    raw_item_desc=item.item_description,
                    unit=item.unit_raw,
                    unit_price=item.unit_price,
                    currency=item.currency,
                )
            )
            existing_keys.add(row_key)
            imported_line_items += 1

    return {
        "contracts": imported_contracts,
        "versions": imported_versions,
        "line_items": imported_line_items,
    }


async def _generate_structuring_export_async(
    run_id: UUID,
    export_format: str,
    user_id: UUID,
    tenant_id: UUID,
) -> dict:
    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_id)

        confirmed_items = list(
            (
                await db.execute(
                    select(ExtractedLineItem).where(
                        ExtractedLineItem.run_id == run_id,
                        ExtractedLineItem.tenant_id == tenant_id,
                        ExtractedLineItem.review_status == "CONFIRMED",
                    )
                )
            ).scalars()
        )

        clauses = list(
            (
                await db.execute(
                    select(ExtractedClause).where(
                        ExtractedClause.run_id == run_id,
                        ExtractedClause.tenant_id == tenant_id,
                    )
                )
            ).scalars()
        )

        if export_format == "LEAKSIGHT_IMPORT" and not confirmed_items:
            logger.info(
                "tool_a_leaksight_import_skipped_no_confirmed_items",
                run_id=str(run_id),
                tenant_id=str(tenant_id),
            )
            return {
                "status": "skipped",
                "reason": "NO_CONFIRMED_ITEMS",
                "run_id": str(run_id),
            }

        excel_docs, contracts_payload, csv_rows = _build_export_payload(confirmed_items, clauses)

        base_dir = Path(get_settings().document_storage_path) / str(tenant_id) / "structuring_exports"
        base_dir.mkdir(parents=True, exist_ok=True)

        if export_format == "EXCEL":
            out_path = base_dir / f"{run_id}_structuring.xlsx"
            export_structuring_excel(out_path, excel_docs)
        elif export_format == "ERP_JSON":
            out_path = base_dir / f"{run_id}_erp.json"
            export_erp_json(out_path, str(run_id), str(tenant_id), contracts_payload)
        elif export_format == "ERP_CSV":
            out_path = base_dir / f"{run_id}_erp.csv"
            export_erp_csv(out_path, csv_rows)
        elif export_format == "LEAKSIGHT_IMPORT":
            import_summary = await _import_confirmed_items_to_leaksight(
                db=db,
                tenant_id=tenant_id,
                confirmed_items=confirmed_items,
                clauses=clauses,
            )
            out_path = base_dir / f"{run_id}_leaksight_import.json"
            export_erp_json(out_path, str(run_id), str(tenant_id), contracts_payload)
            logger.info(
                "tool_a_leaksight_import_completed",
                run_id=str(run_id),
                tenant_id=str(tenant_id),
                contracts=import_summary["contracts"],
                versions=import_summary["versions"],
                line_items=import_summary["line_items"],
            )
        else:
            raise ValueError(f"Unsupported export_format: {export_format}")

        record = ContractStructuringExport(
            tenant_id=tenant_id,
            run_id=run_id,
            export_format=export_format,
            file_path=str(out_path),
            line_items_included=len(confirmed_items),
            generated_by_user_id=user_id,
        )
        db.add(record)
        await db.commit()

        return {
            "status": "success",
            "run_id": str(run_id),
            "export_id": str(record.id),
            "file_path": str(out_path),
        }


@celery_app.task(
    name="backend.app.tools.contract_structuring.tasks.structure_single_contract",
    queue="structuring",
    bind=True,
    max_retries=2,
)
def structure_single_contract(self, document_id: str, run_document_id: str, tenant_id: str):
    final_failure = self.request.retries >= self.max_retries
    try:
        return _run_async(
            _structure_single_contract_async(
                UUID(document_id),
                UUID(run_document_id),
                UUID(tenant_id),
                final_failure=final_failure,
            )
        )
    except Exception as exc:
        logger.error(
            "tool_a_structure_single_contract_failed",
            document_id=document_id,
            run_document_id=run_document_id,
            tenant_id=tenant_id,
            error_type=type(exc).__name__,
        )
        if final_failure:
            raise
        raise self.retry(exc=exc)


@celery_app.task(
    name="backend.app.tools.contract_structuring.tasks.update_structuring_run_status",
    queue="structuring",
)
def update_structuring_run_status(run_id: str, tenant_id: str):
    return _run_async(_update_structuring_run_status_async(UUID(run_id), UUID(tenant_id)))


@celery_app.task(
    name="backend.app.tools.contract_structuring.tasks.generate_structuring_export",
    queue="structuring",
)
def generate_structuring_export(run_id: str, export_format: str, user_id: str, tenant_id: str):
    return _run_async(
        _generate_structuring_export_async(
            run_id=UUID(run_id),
            export_format=export_format,
            user_id=UUID(user_id),
            tenant_id=UUID(tenant_id),
        )
    )
