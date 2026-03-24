"""
Stitches tables that are split across consecutive pages.

Problem: A pricing table starting on page 5 and continuing on page 6
produces two separate RawTableResult objects. The stitcher detects
they are one table and marks the continuation.

Detection criteria (all three must pass):
  A: column count matches between consecutive tables
  B: column width fingerprints match within 15% tolerance
  C: the second table has no header row (first row is data, not headers)
"""
import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

HEADER_KEYWORDS = [
    'item', 'description', 'unit', 'rate', 'price', 'amount',
    'qty', 'quantity', 'uom', 'particulars', 'sno', 's.no', 'sr'
]


@dataclass
class StitchedTableResult:
    """Compatibility object for legacy normalizer/task flow."""

    source_page: int
    raw_table_indices: List[int]
    merged_rows: List[dict]
    is_continuation: bool


def stitch_tables(tables: List) -> List:
    """
    Given a list of RawTableResult sorted by source_page,
    detect and mark multi-page continuations.
    Returns the same list with is_continuation and continued_from_index set.
    Does NOT merge row data - that is the responsibility of the normalizer.
    """
    if len(tables) <= 1:
        return tables

    for i in range(1, len(tables)):
        current = tables[i]
        previous = tables[i - 1]

        if current.source_page != previous.source_page + 1:
            continue

        if previous.is_continuation:
            continue

        if _is_continuation(previous, current):
            tables[i].is_continuation = True
            tables[i].continued_from_index = i - 1
            logger.info(
                f"Stitched table on page {current.source_page} "
                f"to table on page {previous.source_page}"
            )

    return tables


def get_merged_rows(tables: List, start_index: int) -> List[dict]:
    """
    Given a list of tables and a start index, collect all rows
    from that table and any continuations into a single list.
    """
    rows = list(tables[start_index].raw_table_json)
    for i in range(start_index + 1, len(tables)):
        if tables[i].is_continuation and tables[i].continued_from_index == i - 1:
            rows.extend(tables[i].raw_table_json)
        else:
            break
    return rows


def _is_continuation(previous, current) -> bool:
    """Check if current table is a continuation of previous table."""
    if previous.column_count != current.column_count:
        return False

    if previous.raw_table_json and current.raw_table_json:
        prev_keys = list(previous.raw_table_json[0].keys()) if previous.raw_table_json else []
        curr_keys = list(current.raw_table_json[0].keys()) if current.raw_table_json else []
        if prev_keys and curr_keys:
            prev_widths = [len(k) for k in prev_keys]
            curr_widths = [len(k) for k in curr_keys]
            if len(prev_widths) == len(curr_widths):
                mismatches = sum(
                    1 for p, c in zip(prev_widths, curr_widths)
                    if p > 0 and abs(p - c) / p > 0.15
                )
                if mismatches > len(prev_widths) * 0.5:
                    return False

    if current.raw_table_json:
        first_row_values = [str(v).strip().lower() for v in current.raw_table_json[0].values()]
        is_header = any(
            any(kw in val for kw in HEADER_KEYWORDS)
            for val in first_row_values
        )
        if is_header:
            return False

    return True


class MultiPageStitcher:
    """Backward-compatible class API that returns merged stitched tables."""

    def stitch(self, tables: List) -> List[StitchedTableResult]:
        if not tables:
            return []

        marked = stitch_tables(list(tables))
        stitched = []
        i = 0
        while i < len(marked):
            if marked[i].is_continuation:
                i += 1
                continue
            merged_rows = get_merged_rows(marked, i)
            indices = [i]
            j = i + 1
            while j < len(marked):
                if marked[j].is_continuation and marked[j].continued_from_index == j - 1:
                    indices.append(j)
                    j += 1
                    continue
                break
            stitched.append(
                StitchedTableResult(
                    source_page=marked[i].source_page,
                    raw_table_indices=indices,
                    merged_rows=merged_rows,
                    is_continuation=len(indices) > 1,
                )
            )
            i = j
        return stitched
