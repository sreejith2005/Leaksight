from backend.app.tools.contract_structuring.extractors.table_normalizer import extract_currency_from_cell


tests = [
    ("$ 120", (120.0, "USD")),
    ("\u20b910,000", (10000.0, "INR")),
    ("USD 500.50", (500.5, "USD")),
    ("Rs. 250", (250.0, "INR")),
    ("\u20ac 89", (89.0, "EUR")),
    ("\u00a3 200", (200.0, "GBP")),
    ("1500", (1500.0, None)),
    ("", (None, None)),
]

passed = 0
for cell, expected in tests:
    result = extract_currency_from_cell(cell)
    label = cell.encode("unicode_escape").decode("ascii")
    if result == expected:
        print(f"PASS: {label!r} -> {result}")
        passed += 1
    else:
        print(f"FAIL: {label!r} -> got {result}, expected {expected}")

print(f"\n{passed}/{len(tests)} passed")
assert passed == len(tests), "Currency detection has failures"
