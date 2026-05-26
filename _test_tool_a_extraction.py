r"""
Manual verification script for Tool A extraction pipeline.
Run: .venv\Scripts\python.exe _test_tool_a_extraction.py

Uses the existing demo contract files from data/demo/ if available,
otherwise creates a minimal test Excel file.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app.tools.contract_structuring.extractors import structure_contract


def create_test_excel():
    """Create a minimal test pricing Excel file."""
    import pandas as pd
    import tempfile
    data = {
        'Item Description': ['Steel Pipe 20mm', 'Gate Valve', 'Safety Helmet'],
        'Unit': ['Nos', 'Nos', 'Nos'],
        'Unit Price': [850.00, 3500.00, 650.00],
        'Currency': ['INR', 'INR', 'INR'],
    }
    df = pd.DataFrame(data)
    path = os.path.join(tempfile.gettempdir(), 'test_contract.xlsx')
    df.to_excel(path, index=False)
    return path


if __name__ == '__main__':
    test_paths = [
        'data/demo_tool_a/CTR-TOOL-001.pdf',
        'data/demo_tool_a/CTR-TOOL-001.xlsx',
    ]

    test_file = None
    for p in test_paths:
        if os.path.exists(p):
            test_file = p
            break

    if not test_file:
        print("No demo file found - creating test Excel file...")
        test_file = create_test_excel()
        print(f"Created: {test_file}")

    print(f"\nRunning extraction on: {test_file}")
    print("=" * 60)

    line_items, clauses, version_number, base_contract_id = structure_contract(test_file)

    print(f"\nRESULTS:")
    print(f"  Line items extracted: {len(line_items)}")
    print(f"  Clauses extracted:    {len(clauses)}")
    print(f"  Version number:       {version_number}")
    print(f"  Base contract ID:     {base_contract_id}")

    if line_items:
        print(f"\nLINE ITEMS:")
        for i, item in enumerate(line_items, 1):
            print(f"  {i}. {item.item_description} | {item.unit_raw} | "
                  f"Price: {item.unit_price} | "
                  f"Confidence: item={item.item_confidence:.2f} "
                  f"price={item.price_confidence:.2f} "
                  f"unit={item.unit_confidence:.2f} | "
                  f"NeedsReview: {item.needs_review}")

    if clauses:
        print(f"\nCLAUSES:")
        for c in clauses:
            print(f"  {c.clause_type}: {c.extracted_value} "
                  f"(confidence={c.confidence:.2f}, needs_review={c.needs_review})")

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
