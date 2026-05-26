"""
PDF extractor with tiered table/text/OCR strategy.
"""

from __future__ import annotations

import gc
import logging
import multiprocessing
import queue
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Callable, List

from backend.app.tools.contract_structuring.extractors.base_extractor import (
    DocumentExtractionResult,
    RawTableResult,
)
from backend.app.tools.contract_structuring.extractors.table_normalizer import (
    LINE_ITEM_PATTERN,
    extract_currency_from_cell,
    normalize_tables_detailed,
)

logger = logging.getLogger(__name__)

_OCR_PAGE_TIMEOUT_SECONDS = 120
_OCR_RENDER_SCALES = (2.0, 1.5, 1.0)
_OCR_CACHE: dict[str, dict[str, Any]] = {}
_PADDLE_OCR_CONFIG = {
    "use_angle_cls": False,
    "lang": "en",
    "use_gpu": False,
    "show_log": False,
    "enable_mkldnn": False,
    "det_limit_side_len": 960,
    "det_model_dir": None,
    "rec_model_dir": None,
    "cls_model_dir": None,
    "use_mp": False,
    "total_process_num": 1,
}


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def _sanitize_headers(values: list[str]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(values, start=1):
        cleaned = _clean_cell(value) or f"column_{index}"
        seen[cleaned] = seen.get(cleaned, 0) + 1
        if seen[cleaned] > 1:
            cleaned = f"{cleaned}_{seen[cleaned]}"
        headers.append(cleaned)
    return headers


def _table_has_data_rows(rows: list[dict[str, str]]) -> bool:
    return bool(rows) and any(any(_clean_cell(value) for value in row.values()) for row in rows)


def _make_raw_table(
    source_page: int,
    method: str,
    rows: list[dict[str, str]],
    confidence: float,
    source_name: str | None = None,
) -> RawTableResult:
    return RawTableResult(
        source_page=source_page,
        extraction_method=method,
        raw_table_json=rows,
        table_confidence=confidence,
        column_count=len(rows[0]) if rows else 0,
        row_count=len(rows),
        source_name=source_name,
        source_row_count=len(rows),
    )


def _matrix_to_rows(table: list[list[Any]]) -> tuple[list[str], list[dict[str, str]]]:
    if not table or len(table) < 2:
        return [], []
    headers = _sanitize_headers([_clean_cell(cell) for cell in table[0]])
    rows = [
        {
            headers[index]: _clean_cell(row[index]) if index < len(row) else ""
            for index in range(len(headers))
        }
        for row in table[1:]
    ]
    return headers, rows


def _extract_text_pages(document_path: str) -> list[str]:
    try:
        import pdfplumber

        with pdfplumber.open(document_path) as pdf:
            return [_clean_cell(page.extract_text() or "") for page in pdf.pages]
    except Exception as exc:
        logger.debug("pdfplumber text extraction failed: %s", exc)
        return []


def _extract_full_text(document_path: str) -> str:
    return "\n".join(page_text for page_text in _extract_text_pages(document_path) if page_text).strip()


def _is_scanned_pdf(document_path: str) -> bool:
    pages = _extract_text_pages(document_path)
    return sum(len(page_text) for page_text in pages) < 100


def _try_pdfplumber_default(document_path: str) -> list[RawTableResult]:
    results: list[RawTableResult] = []
    import pdfplumber

    with pdfplumber.open(document_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables(table_settings={}) or []
            for table_index, table in enumerate(tables, start=1):
                _headers, rows = _matrix_to_rows(table)
                if not _table_has_data_rows(rows):
                    continue
                results.append(_make_raw_table(page_number, "PDFPLUMBER", rows, 0.65, f"default_{table_index}"))
    return results


def _try_pdfplumber_text(document_path: str) -> list[RawTableResult]:
    results: list[RawTableResult] = []
    import pdfplumber

    with pdfplumber.open(document_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables(
                table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                }
            ) or []
            for table_index, table in enumerate(tables, start=1):
                _headers, rows = _matrix_to_rows(table)
                if not _table_has_data_rows(rows):
                    continue
                results.append(_make_raw_table(page_number, "PDFPLUMBER", rows, 0.60, f"text_{table_index}"))
    return results


def _explicit_lines_from_words(page) -> tuple[list[float], list[float]]:
    words = page.extract_words(keep_blank_chars=False) or []
    if not words:
        return [], []

    vertical_candidates: list[float] = [page.bbox[0], page.bbox[2]]
    horizontal_candidates: list[float] = [page.bbox[1], page.bbox[3]]

    for word in words:
        vertical_candidates.extend([round(float(word["x0"]), 1), round(float(word["x1"]), 1)])
        horizontal_candidates.extend([round(float(word["top"]), 1), round(float(word["bottom"]), 1)])

    def _dedupe(values: list[float], tolerance: float) -> list[float]:
        deduped: list[float] = []
        for value in sorted(values):
            if not deduped or abs(value - deduped[-1]) > tolerance:
                deduped.append(value)
        return deduped

    return _dedupe(vertical_candidates, 8.0), _dedupe(horizontal_candidates, 6.0)


def _try_pdfplumber_explicit_lines(document_path: str) -> list[RawTableResult]:
    results: list[RawTableResult] = []
    import pdfplumber

    with pdfplumber.open(document_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            vertical_lines, horizontal_lines = _explicit_lines_from_words(page)
            if len(vertical_lines) < 3 or len(horizontal_lines) < 3:
                continue
            tables = page.extract_tables(
                table_settings={
                    "vertical_strategy": "explicit",
                    "horizontal_strategy": "explicit",
                    "explicit_vertical_lines": vertical_lines,
                    "explicit_horizontal_lines": horizontal_lines,
                }
            ) or []
            for table_index, table in enumerate(tables, start=1):
                _headers, rows = _matrix_to_rows(table)
                if not _table_has_data_rows(rows):
                    continue
                results.append(_make_raw_table(page_number, "PDFPLUMBER", rows, 0.62, f"explicit_{table_index}"))
    return results


def _try_pdfplumber(document_path: str, start_page: int | None = None, end_page: int | None = None, exclude_pages: set | None = None) -> list[RawTableResult]:
    _ = start_page, end_page, exclude_pages
    return _try_pdfplumber_default(document_path)


def _try_camelot_lattice(document_path: str, page_range: str | None = None) -> list[RawTableResult]:
    results: list[RawTableResult] = []
    import camelot

    tables = camelot.read_pdf(document_path, pages=page_range or "all", flavor="lattice")
    for table_index, table in enumerate(tables, start=1):
        if table.df.empty or len(table.df) < 2:
            continue
        headers = _sanitize_headers([_clean_cell(value) for value in table.df.iloc[0].tolist()])
        rows = [
            {
                headers[index]: _clean_cell(values[index]) if index < len(values) else ""
                for index in range(len(headers))
            }
            for values in table.df.iloc[1:].values.tolist()
        ]
        if not _table_has_data_rows(rows):
            continue
        results.append(
            _make_raw_table(
                int(getattr(table, "page", 1) or 1),
                "CAMELOT_LATTICE",
                rows,
                min(0.95, 0.55 + (float(getattr(table, "accuracy", 0.0) or 0.0) / 100.0) * 0.35),
                f"lattice_{table_index}",
            )
        )
    return results


def _try_camelot_stream(document_path: str, page_range: str | None = None, exclude_pages: set | None = None) -> list[RawTableResult]:
    results: list[RawTableResult] = []
    import camelot

    tables = camelot.read_pdf(document_path, pages=page_range or "all", flavor="stream", edge_tol=500)
    excluded = exclude_pages or set()
    for table_index, table in enumerate(tables, start=1):
        if int(getattr(table, "page", 1) or 1) in excluded:
            continue
        if table.df.empty or len(table.df) < 2:
            continue
        headers = _sanitize_headers([_clean_cell(value) for value in table.df.iloc[0].tolist()])
        rows = [
            {
                headers[index]: _clean_cell(values[index]) if index < len(values) else ""
                for index in range(len(headers))
            }
            for values in table.df.iloc[1:].values.tolist()
        ]
        if not _table_has_data_rows(rows):
            continue
        results.append(
            _make_raw_table(
                int(getattr(table, "page", 1) or 1),
                "CAMELOT_STREAM",
                rows,
                min(0.90, 0.50 + (float(getattr(table, "accuracy", 0.0) or 0.0) / 100.0) * 0.35),
                f"stream_{table_index}",
            )
        )
    return results


def _extract_line_items_from_text(full_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for match in LINE_ITEM_PATTERN.finditer(full_text or ""):
        groups = match.groupdict()
        price_value, currency = extract_currency_from_cell(groups.get("price", ""))
        if price_value is None:
            continue
        rows.append(
            {
                "Item Description": groups.get("item", "").strip(),
                "Quantity": groups.get("quantity", "").strip(),
                "Unit": groups.get("unit", "").strip(),
                "Unit Price": str(price_value),
                "Currency": currency or "",
            }
        )
    return rows


def _pdf_text_fallback_tables(document_path: str, full_text: str) -> list[RawTableResult]:
    rows = _extract_line_items_from_text(full_text)
    if not rows:
        return []
    return [
        _make_raw_table(
            source_page=1,
            method="PDFPLUMBER",
            rows=rows,
            confidence=0.40,
            source_name=f"{Path(document_path).name}:text_regex",
        )
    ]


def _build_extraction_result(
    tables: list[RawTableResult],
    full_text: str,
    failure_flags: list[str] | None = None,
) -> DocumentExtractionResult:
    normalization = normalize_tables_detailed(tables, stitched=True, document_text=full_text)
    flags = list(failure_flags or [])
    flags.extend(normalization.failure_flags)
    return DocumentExtractionResult(
        tables=tables,
        line_items=normalization.line_items,
        clauses=[],
        confidence=normalization.confidence,
        failure_flags=list(dict.fromkeys(flags)),
        text=full_text,
    )


def _tier_attempt(
    tier_name: str,
    extractor: Callable[[], list[RawTableResult]],
    attempt_log: list[str],
) -> list[RawTableResult]:
    try:
        tables = extractor()
    except Exception as exc:
        reason = f"{tier_name}:ERROR:{type(exc).__name__}"
        attempt_log.append(reason)
        logger.info("tool_a_pdf_tier_failed %s", reason)
        return []

    if tables and any(_table_has_data_rows(table.raw_table_json) for table in tables):
        attempt_log.append(f"{tier_name}:SUCCESS:{len(tables)}")
        logger.info("tool_a_pdf_tier_succeeded tier=%s tables=%s", tier_name, len(tables))
        return tables

    attempt_log.append(f"{tier_name}:NO_TABLES")
    logger.info("tool_a_pdf_tier_empty tier=%s", tier_name)
    return []


def _extract_pdf_document(document_path: str) -> DocumentExtractionResult:
    path = Path(document_path)
    if not path.exists():
        logger.error("PDF not found: %s", document_path)
        return DocumentExtractionResult(failure_flags=["PDF_NOT_FOUND"])

    full_text = _extract_full_text(document_path)
    attempt_log: list[str] = []
    tiers: list[tuple[str, Callable[[], list[RawTableResult]]]] = [
        ("TIER_1_PDFPLUMBER_DEFAULT", lambda: _try_pdfplumber_default(document_path)),
        ("TIER_2_PDFPLUMBER_TEXT", lambda: _try_pdfplumber_text(document_path)),
        ("TIER_3_PDFPLUMBER_EXPLICIT_LINES", lambda: _try_pdfplumber_explicit_lines(document_path)),
        ("TIER_4_CAMELOT_LATTICE", lambda: _try_camelot_lattice(document_path, "all")),
        ("TIER_5_CAMELOT_STREAM", lambda: _try_camelot_stream(document_path, "all")),
        ("TIER_6_TEXT_REGEX", lambda: _pdf_text_fallback_tables(document_path, full_text)),
    ]

    for tier_name, tier_fn in tiers:
        tables = _tier_attempt(tier_name, tier_fn, attempt_log)
        if tables:
            return _build_extraction_result(
                tables,
                full_text,
                failure_flags=[f"PDF_TIER_SUCCESS:{tier_name}"],
            )

    if _is_scanned_pdf(document_path):
        attempt_log.append("TIER_7_SCANNED_PDF_DETECTED")
        logger.info("tool_a_pdf_scanned_detected path=%s", document_path)
        ocr_payload = _extract_pdf_via_page_ocr(document_path)
        ocr_tables = list(ocr_payload.get("tables", []) or [])
        if ocr_tables:
            attempt_log.append(f"TIER_7_PADDLE_OCR:SUCCESS:{len(ocr_tables)}")
            logger.info("tool_a_pdf_tier_succeeded tier=TIER_7_PADDLE_OCR tables=%s", len(ocr_tables))
            text = ocr_payload.get("text") or full_text
            return _build_extraction_result(
                ocr_tables,
                text,
                failure_flags=["PDF_TIER_SUCCESS:TIER_7_PADDLE_OCR", "SCANNED_PDF_DETECTED"],
            )
        attempt_log.append("TIER_7_PADDLE_OCR:NO_TABLES")
        logger.info("tool_a_pdf_tier_empty tier=TIER_7_PADDLE_OCR")
    else:
        attempt_log.append("TIER_7_SKIPPED_NOT_SCANNED")
        logger.info("tool_a_pdf_tier_skipped tier=TIER_7_PADDLE_OCR reason=not_scanned")

    return DocumentExtractionResult(
        tables=[],
        line_items=[],
        clauses=[],
        confidence=0.10,
        failure_flags=[f"PDF_EXTRACTION_FAILED:{'|'.join(attempt_log)}"],
        text=full_text,
    )


def extract_tables_from_pdf(document_path: str) -> List[RawTableResult]:
    return _extract_pdf_document(document_path).tables


def extract_text_from_pdf(document_path: str) -> str:
    result = _extract_pdf_document(document_path)
    if result.text:
        return result.text
    return _extract_pdf_via_page_ocr(document_path)["text"]


def _extract_pdf_via_page_ocr(document_path: str) -> dict[str, Any]:
    cache_key = _build_cache_key(document_path)
    cached = _OCR_CACHE.get(cache_key) if cache_key else None
    if cached is not None:
        return cached

    page_count = _get_pdf_page_count(document_path)
    tables: list[RawTableResult] = []
    text_parts: list[str] = []

    for page_index in range(page_count):
        page_number = page_index + 1
        payload = _process_page_with_timeout(document_path, page_index)
        if payload["status"] == "timeout":
            logger.warning("tool_a_pdf_ocr_page_timeout page=%s", page_number)
            continue
        if payload["status"] != "success":
            logger.warning("tool_a_pdf_ocr_page_failed page=%s error=%s", page_number, payload.get("error"))
            continue

        page_text = str(payload.get("text", "")).strip()
        if page_text:
            text_parts.append(page_text)

        page_rows = list(payload.get("rows") or [])
        if page_rows:
            tables.append(
                RawTableResult(
                    source_page=page_number,
                    extraction_method="PADDLE_OCR",
                    raw_table_json=page_rows,
                    table_confidence=_ocr_table_confidence(payload.get("confidences") or []),
                    column_count=max((len(row) for row in page_rows), default=0),
                    row_count=len(page_rows),
                    source_name=f"ocr_page_{page_number}",
                    source_row_count=len(page_rows),
                )
            )
        gc.collect()

    result = {"tables": tables, "text": "\n".join(text_parts).strip()}
    if cache_key:
        _OCR_CACHE[cache_key] = result
    return result


def _process_page_with_timeout(document_path: str, page_index: int) -> dict[str, Any]:
    ctx = multiprocessing.get_context("spawn" if sys.platform == "win32" else "spawn")
    result_queue: multiprocessing.Queue = ctx.Queue()
    process = ctx.Process(target=_ocr_page_worker, args=(document_path, page_index, result_queue))
    process.daemon = True
    process.start()
    process.join(_OCR_PAGE_TIMEOUT_SECONDS)

    if process.is_alive():
        process.terminate()
        process.join(5)
        _close_queue(result_queue)
        return {"status": "timeout"}

    try:
        payload = result_queue.get_nowait()
    except queue.Empty:
        payload = {"status": "error", "error": f"OCR worker exited without a result (exitcode={process.exitcode})"}
    finally:
        _close_queue(result_queue)

    return payload


def _ocr_page_worker(document_path: str, page_index: int, result_queue) -> None:
    image = None
    try:
        image = _render_page_to_image(document_path, page_index)
        payload = _ocr_image_payload(image)
        result_queue.put({"status": "success", **payload})
    except Exception as exc:
        result_queue.put({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        if image is not None:
            del image
        gc.collect()


def _render_page_to_image(document_path: str, page_index: int):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(document_path)
    page = pdf[page_index]
    bitmap = None
    try:
        last_error: Exception | None = None
        for scale in _OCR_RENDER_SCALES:
            try:
                bitmap = page.render(scale=scale)
                return bitmap.to_pil()
            except Exception as exc:
                last_error = exc
                gc.collect()
            finally:
                if bitmap is not None:
                    del bitmap
                    bitmap = None

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unable to render PDF page for OCR")
    finally:
        if hasattr(page, "close"):
            page.close()
        if hasattr(pdf, "close"):
            pdf.close()


def _ocr_image_payload(image) -> dict[str, Any]:
    import numpy as np
    from paddleocr import PaddleOCR

    _force_paddle_ir_optim_off()
    ocr = PaddleOCR(**_PADDLE_OCR_CONFIG)
    result = ocr.ocr(np.array(image), cls=False)

    text_lines: list[str] = []
    confidences: list[float] = []
    structured_cells: list[dict[str, Any]] = []
    for line in (result[0] if result else []) or []:
        if len(line) < 2:
            continue
        box = line[0]
        payload = line[1]
        text = payload[0] if isinstance(payload, (list, tuple)) else str(payload)
        confidence = payload[1] if isinstance(payload, (list, tuple)) and len(payload) > 1 else 0.5
        normalized_text = str(text).strip()
        if not normalized_text:
            continue
        text_lines.append(normalized_text)
        confidences.append(float(confidence))
        structured_cells.append(_cell_from_box(box, normalized_text))

    return {
        "text": "\n".join(text_lines),
        "rows": _ocr_rows_to_dicts(_group_cells_into_rows(structured_cells)),
        "confidences": confidences,
    }


def _cell_from_box(box: Any, text: str) -> dict[str, Any]:
    points = box if isinstance(box, list) else []
    xs = [float(point[0]) for point in points] if points else [0.0]
    ys = [float(point[1]) for point in points] if points else [0.0]
    return {"text": text, "x": min(xs), "y": sum(ys) / len(ys), "height": max(1.0, max(ys) - min(ys))}


def _group_cells_into_rows(cells: list[dict[str, Any]]) -> list[list[str]]:
    if not cells:
        return []

    row_threshold = max(12.0, mean(cell["height"] for cell in cells) * 0.7)
    ordered_cells = sorted(cells, key=lambda cell: (cell["y"], cell["x"]))

    grouped_rows: list[dict[str, Any]] = []
    for cell in ordered_cells:
        if not grouped_rows or abs(cell["y"] - grouped_rows[-1]["anchor_y"]) > row_threshold:
            grouped_rows.append({"anchor_y": cell["y"], "cells": [cell]})
            continue
        grouped_rows[-1]["cells"].append(cell)
        grouped_rows[-1]["anchor_y"] = mean(existing_cell["y"] for existing_cell in grouped_rows[-1]["cells"])

    rows: list[list[str]] = []
    for grouped_row in grouped_rows:
        texts = [cell["text"] for cell in sorted(grouped_row["cells"], key=lambda value: value["x"])]
        if len(texts) >= 2:
            rows.append(texts)
    return rows


def _ocr_rows_to_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    if len(rows) < 2:
        return []

    max_cols = max(len(row) for row in rows)
    headers = _sanitize_headers(rows[0] + [""] * (max_cols - len(rows[0])))
    results: list[dict[str, str]] = []
    for row in rows[1:]:
        padded = list(row) + [""] * (max_cols - len(row))
        row_dict = {headers[index]: _clean_cell(padded[index]) for index in range(max_cols)}
        if sum(1 for value in row_dict.values() if value) >= 2:
            results.append(row_dict)
    return results


def _ocr_table_confidence(confidences: list[float]) -> float:
    if not confidences:
        return 0.40
    return round(max(0.40, min(0.85, mean(float(confidence) for confidence in confidences))), 4)


def _build_cache_key(document_path: str) -> str | None:
    path = Path(document_path)
    try:
        stat = path.resolve().stat()
    except OSError:
        return None
    return f"{path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"


def _get_pdf_page_count(document_path: str) -> int:
    try:
        import fitz

        doc = fitz.open(document_path)
        total_pages = len(doc)
        doc.close()
        return total_pages
    except Exception:
        try:
            import pdfplumber

            with pdfplumber.open(document_path) as pdf:
                return len(pdf.pages)
        except Exception as exc:
            logger.error("Cannot determine page count: %s", exc)
            return 0


def _close_queue(result_queue) -> None:
    try:
        result_queue.close()
    except Exception:
        pass
    try:
        result_queue.join_thread()
    except Exception:
        pass


def _force_paddle_ir_optim_off() -> None:
    from paddle import inference

    current = inference.Config.switch_ir_optim
    if getattr(current, "_leaksight_forced_false", False):
        return

    original = current

    def _switch_ir_optim_disabled(self, _flag):
        return original(self, False)

    _switch_ir_optim_disabled._leaksight_forced_false = True
    inference.Config.switch_ir_optim = _switch_ir_optim_disabled


class PdfExtractor:
    def extract_tables(self, document_path):
        return extract_tables_from_pdf(str(document_path))

    def extract_text(self, document_path):
        return extract_text_from_pdf(str(document_path))

    def extract(self, document_path):
        return _extract_pdf_document(str(document_path))


PDFExtractor = PdfExtractor
