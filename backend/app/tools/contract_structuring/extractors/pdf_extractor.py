"""
PDF table extractor - three-tier strategy:
  Tier 1: camelot lattice (bordered tables)    -> confidence 0.85-1.0
  Tier 2: camelot stream (borderless tables)   -> confidence 0.60-0.85
  Tier 3: pdfplumber fallback                  -> confidence 0.40-0.70

If all digital extraction fails, fall back to page-by-page OCR using
`pypdfium2` so scanned PDFs do not exhaust memory or hang the worker.
"""

from __future__ import annotations

import gc
import logging
import multiprocessing
import queue
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any, List

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
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


def extract_tables_from_pdf(document_path: str) -> List["RawTableResult"]:
    """
    Extract all pricing tables from a PDF document.
    Returns list of RawTableResult sorted by source_page.
    Never raises - on any error, logs and returns empty list.
    """
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult

    path = Path(document_path)
    if not path.exists():
        logger.error("PDF not found: %s", document_path)
        return []

    results: list[RawTableResult] = []
    total_pages = _get_pdf_page_count(document_path)
    if total_pages <= 0:
        return []

    for batch_start in range(1, total_pages + 1, _BATCH_SIZE):
        batch_end = min(batch_start + _BATCH_SIZE - 1, total_pages)
        page_range = f"{batch_start}-{batch_end}"

        tier1_results = _try_camelot_lattice(document_path, page_range)
        results.extend(tier1_results)

        pages_with_tier1 = {r.source_page for r in tier1_results if r.table_confidence >= 0.6}
        tier2_results = _try_camelot_stream(document_path, page_range, exclude_pages=pages_with_tier1)
        results.extend(tier2_results)

        pages_covered = pages_with_tier1 | {r.source_page for r in tier2_results if r.table_confidence >= 0.5}
        tier3_results = _try_pdfplumber(document_path, batch_start, batch_end, exclude_pages=pages_covered)
        results.extend(tier3_results)

    if results:
        return sorted(results, key=lambda r: r.source_page)

    ocr_payload = _extract_pdf_via_page_ocr(document_path)
    return sorted(ocr_payload["tables"], key=lambda r: r.source_page)


def _try_camelot_lattice(document_path: str, page_range: str) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult

    results = []
    try:
        import camelot

        tables = camelot.read_pdf(document_path, pages=page_range, flavor="lattice")
        for table in tables:
            if table.df.empty or len(table.df) < 2:
                continue
            rows = table.df.to_dict("records")
            results.append(
                RawTableResult(
                    source_page=table.page,
                    extraction_method="CAMELOT_LATTICE",
                    raw_table_json=_clean_rows(rows),
                    table_confidence=min(1.0, 0.7 + (table.accuracy / 100) * 0.3),
                    column_count=len(table.df.columns),
                    row_count=len(table.df),
                )
            )
    except Exception as exc:
        logger.debug("Camelot lattice failed for %s: %s", page_range, exc)
    return results


def _try_camelot_stream(document_path: str, page_range: str, exclude_pages: set) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult

    results = []
    try:
        import camelot

        tables = camelot.read_pdf(document_path, pages=page_range, flavor="stream")
        for table in tables:
            if table.page in exclude_pages:
                continue
            if table.df.empty or len(table.df) < 2:
                continue
            rows = table.df.to_dict("records")
            results.append(
                RawTableResult(
                    source_page=table.page,
                    extraction_method="CAMELOT_STREAM",
                    raw_table_json=_clean_rows(rows),
                    table_confidence=min(0.85, 0.5 + (table.accuracy / 100) * 0.35),
                    column_count=len(table.df.columns),
                    row_count=len(table.df),
                )
            )
    except Exception as exc:
        logger.debug("Camelot stream failed for %s: %s", page_range, exc)
    return results


def _try_pdfplumber(document_path: str, start_page: int, end_page: int, exclude_pages: set) -> List:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult

    results = []
    try:
        import pdfplumber

        with pdfplumber.open(document_path) as pdf:
            for page_num in range(start_page, end_page + 1):
                if page_num in exclude_pages:
                    continue
                if page_num > len(pdf.pages):
                    break
                page = pdf.pages[page_num - 1]
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header = [str(c).strip() if c else "" for c in table[0]]
                    rows = [dict(zip(header, [str(c).strip() if c else "" for c in row])) for row in table[1:]]
                    results.append(
                        RawTableResult(
                            source_page=page_num,
                            extraction_method="PDFPLUMBER",
                            raw_table_json=rows,
                            table_confidence=0.55,
                            column_count=len(header),
                            row_count=len(rows),
                        )
                    )
    except Exception as exc:
        logger.debug("pdfplumber failed for pages %s-%s: %s", start_page, end_page, exc)
    return results


def extract_text_from_pdf(document_path: str) -> str:
    """Extract full text from PDF for clause extraction. Returns empty string on failure."""
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(document_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        joined_text = "\n".join(text_parts).strip()
        if joined_text:
            return joined_text
    except Exception as exc:
        logger.error("Text extraction failed: %s", exc)

    return _extract_pdf_via_page_ocr(document_path)["text"]


def _extract_pdf_via_page_ocr(document_path: str) -> dict[str, Any]:
    from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult

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
            logger.warning(
                "tool_a_pdf_ocr_page_timeout",
                extra={"document_path": document_path, "page_number": page_number},
            )
            continue

        if payload["status"] != "success":
            logger.warning(
                "tool_a_pdf_ocr_page_failed",
                extra={
                    "document_path": document_path,
                    "page_number": page_number,
                    "error": payload.get("error"),
                },
            )
            continue

        page_text = str(payload.get("text", "")).strip()
        if page_text:
            text_parts.append(page_text)

        page_rows = payload.get("rows") or []
        row_count = len(page_rows)
        if row_count:
            tables.append(
                RawTableResult(
                    source_page=page_number,
                    extraction_method="PADDLE_OCR",
                    raw_table_json=page_rows,
                    table_confidence=_ocr_table_confidence(payload.get("confidences") or []),
                    column_count=max((len(row) for row in page_rows), default=0),
                    row_count=row_count,
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
    process = ctx.Process(
        target=_ocr_page_worker,
        args=(document_path, page_index, result_queue),
    )
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
        payload = {
            "status": "error",
            "error": f"OCR worker exited without a result (exitcode={process.exitcode})",
        }
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
        result_queue.put(
            {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
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
    return {
        "text": text,
        "x": min(xs),
        "y": sum(ys) / len(ys),
        "height": max(1.0, max(ys) - min(ys)),
    }


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
        grouped_rows[-1]["anchor_y"] = mean(
            existing_cell["y"] for existing_cell in grouped_rows[-1]["cells"]
        )

    rows: list[list[str]] = []
    for grouped_row in grouped_rows:
        texts = [cell["text"] for cell in sorted(grouped_row["cells"], key=lambda c: c["x"])]
        if len(texts) >= 2:
            rows.append(texts)
    return rows


def _ocr_rows_to_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    if len(rows) < 2:
        return []

    max_cols = max(len(row) for row in rows)
    header = _sanitize_headers(rows[0], max_cols)
    results: list[dict[str, str]] = []

    for row in rows[1:]:
        padded_row = list(row) + [""] * (max_cols - len(row))
        row_dict = {
            header[idx]: str(value).strip()
            for idx, value in enumerate(padded_row[:max_cols])
        }
        if sum(1 for value in row_dict.values() if value) >= 2:
            results.append(row_dict)

    return results


def _sanitize_headers(header_row: list[str], max_cols: int) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}

    for idx in range(max_cols):
        raw_value = header_row[idx] if idx < len(header_row) else ""
        cleaned = re.sub(r"\s+", " ", str(raw_value).strip()) or f"column_{idx + 1}"
        duplicate_count = seen.get(cleaned, 0)
        seen[cleaned] = duplicate_count + 1
        if duplicate_count:
            cleaned = f"{cleaned}_{duplicate_count + 1}"
        headers.append(cleaned)

    return headers


def _ocr_table_confidence(confidences: list[float]) -> float:
    if not confidences:
        return 0.4
    return round(max(0.4, min(0.85, mean(float(conf) for conf in confidences))), 4)


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


def _clean_rows(rows):
    """Convert all values to strings, strip whitespace."""
    return [{str(k).strip(): str(v).strip() for k, v in row.items()} for row in rows]


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
    """Backward-compatible wrapper for existing class-based extraction flows."""

    def extract_tables(self, document_path):
        return extract_tables_from_pdf(str(document_path))

    def extract_text(self, document_path):
        return extract_text_from_pdf(str(document_path))
