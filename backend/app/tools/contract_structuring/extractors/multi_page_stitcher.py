"""
Stitch only genuinely continuous tables across consecutive pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class StitchedTableResult:
    source_page: int
    raw_table_indices: List[int]
    merged_rows: List[dict]
    is_continuation: bool


def _normalized_headers(table) -> list[str]:
    rows = list(getattr(table, "raw_table_json", []) or [])
    if not rows:
        return []
    return [str(header or "").strip().lower() for header in rows[0].keys()]


def headers_match(table_a, table_b) -> bool:
    headers_a = _normalized_headers(table_a)
    headers_b = _normalized_headers(table_b)
    return bool(headers_a) and headers_a == headers_b


def _row_cells(row: dict) -> list[str]:
    return [str(value or "").strip() for value in row.values()]


def _row_looks_complete(row: dict) -> bool:
    cells = _row_cells(row)
    if len(cells) < 2:
        return False
    return all(cell.strip() for cell in cells[:2])


def should_stitch(table_a, table_b) -> bool:
    if table_b.source_page != table_a.source_page + 1:
        return False

    rows_a = list(getattr(table_a, "raw_table_json", []) or [])
    rows_b = list(getattr(table_b, "raw_table_json", []) or [])
    if not rows_a or not rows_b:
        return False

    if not headers_match(table_a, table_b):
        return False

    last_row_complete = _row_looks_complete(rows_a[-1])
    if last_row_complete:
        return False

    return True


def stitch_tables(tables: List) -> List:
    if len(tables) <= 1:
        return tables

    for index in range(1, len(tables)):
        current = tables[index]
        previous = tables[index - 1]
        if getattr(previous, "is_continuation", False):
            continue
        if should_stitch(previous, current):
            current.is_continuation = True
            current.continued_from_index = index - 1
    return tables


def get_merged_rows(tables: List, start_index: int) -> List[dict]:
    rows = list(getattr(tables[start_index], "raw_table_json", []) or [])
    for index in range(start_index + 1, len(tables)):
        current = tables[index]
        if getattr(current, "is_continuation", False) and getattr(current, "continued_from_index", None) == index - 1:
            rows.extend(list(getattr(current, "raw_table_json", []) or []))
            continue
        break
    return rows


class MultiPageStitcher:
    def stitch(self, tables: List[object]) -> List[StitchedTableResult]:
        if not tables:
            return []

        marked = stitch_tables(list(tables))
        stitched: list[StitchedTableResult] = []
        index = 0
        while index < len(marked):
            if getattr(marked[index], "is_continuation", False):
                index += 1
                continue

            merged_rows = get_merged_rows(marked, index)
            raw_indices = [index]
            cursor = index + 1
            while cursor < len(marked):
                current = marked[cursor]
                if getattr(current, "is_continuation", False) and getattr(current, "continued_from_index", None) == cursor - 1:
                    raw_indices.append(cursor)
                    cursor += 1
                    continue
                break

            stitched.append(
                StitchedTableResult(
                    source_page=marked[index].source_page,
                    raw_table_indices=raw_indices,
                    merged_rows=merged_rows,
                    is_continuation=len(raw_indices) > 1,
                )
            )
            index = cursor
        return stitched
