"""Generate curated demo dataset for LeakSight V1 pilot demo.

Creates exactly known embedded leakage so the system output can be
compared against a predetermined answer key.

Demo dataset spec:
- 3 vendors: Acme Supplies Ltd, BuildRight Materials, TechServ India
- 5 contracts (valid 2024 date ranges)
- 20 invoices in a single file:
    14 clean + 3 price mismatch + 1 qty mismatch + 2 near-duplicates
- 7 POs
- All amounts in INR (no FX complexity)
- All dates in 2024

DUPLICATE DETECTION STRATEGY:
The DB has a UNIQUE constraint on (tenant_id, invoice_no), so exact
duplicate invoice_no resubmission cannot create a second Invoice record.
Rule 2 therefore relies on near-duplicate detection: same vendor, same
total_amount, within 30-day window, DIFFERENT invoice_no, and at least
one shared normalized item_desc.  Two near-duplicate pairs are embedded
in the invoice data to trigger this.

Output files saved to data/demo/:
  - Contracts_Demo.xlsx
  - Invoices_Demo.xlsx        (20 invoices — single file)
  - PO_Demo.xlsx
  - Demo_Expected_Output.xlsx
"""
import pandas as pd
from pathlib import Path
from datetime import date

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "demo"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════
# CONTRACTS — 8 line items across 5 contracts, 3 vendors
# ═══════════════════════════════════════════════════════
contracts = [
    {
        "Contract_ID": "CTR-DEMO-001",
        "Vendor_Name": "Acme Supplies Ltd",
        "Item_Description": "A4 Copier Paper 80gsm",
        "Unit_Price": 350.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
    {
        "Contract_ID": "CTR-DEMO-001",
        "Vendor_Name": "Acme Supplies Ltd",
        "Item_Description": "Executive Office Desk",
        "Unit_Price": 4500.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
    {
        "Contract_ID": "CTR-DEMO-002",
        "Vendor_Name": "BuildRight Materials",
        "Item_Description": "Safety Helmets Industrial Grade",
        "Unit_Price": 800.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
    {
        "Contract_ID": "CTR-DEMO-002",
        "Vendor_Name": "BuildRight Materials",
        "Item_Description": "Steel Reinforcement Bars 12mm",
        "Unit_Price": 52.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
    {
        "Contract_ID": "CTR-DEMO-003",
        "Vendor_Name": "TechServ India",
        "Item_Description": "Cloud Hosting Services Monthly",
        "Unit_Price": 450.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
    {
        "Contract_ID": "CTR-DEMO-003",
        "Vendor_Name": "TechServ India",
        "Item_Description": "Network Cable Cat6 100m",
        "Unit_Price": 1200.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
    {
        "Contract_ID": "CTR-DEMO-004",
        "Vendor_Name": "Acme Supplies Ltd",
        "Item_Description": "Printer Toner Cartridge",
        "Unit_Price": 2800.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
    {
        "Contract_ID": "CTR-DEMO-005",
        "Vendor_Name": "BuildRight Materials",
        "Item_Description": "Cement OPC 53 Grade",
        "Unit_Price": 380.00,
        "Currency": "INR",
        "Effective_Start_Date": date(2024, 1, 1),
        "Effective_End_Date": date(2024, 12, 31),
        "Version_Number": 1,
    },
]

# ═══════════════════════════════════════════════════════
# INVOICES — 20 invoices in a single file
# ═══════════════════════════════════════════════════════
invoices = []

# --- 14 CLEAN invoices ---
invoices.append({"Invoice_Number": "INV-DEMO-001", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "A4 Copier Paper 80gsm", "Quantity": 200, "Unit_Price": 350.00, "Invoice_Date": date(2024, 2, 5), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-002", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "Executive Office Desk", "Quantity": 5, "Unit_Price": 4500.00, "Invoice_Date": date(2024, 2, 15), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-003", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "Printer Toner Cartridge", "Quantity": 20, "Unit_Price": 2800.00, "Invoice_Date": date(2024, 3, 1), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-005", "Vendor_Name": "BuildRight Materials", "Item_Description": "Safety Helmets Industrial Grade", "Quantity": 50, "Unit_Price": 800.00, "Invoice_Date": date(2024, 3, 10), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-006", "Vendor_Name": "BuildRight Materials", "Item_Description": "Steel Reinforcement Bars 12mm", "Quantity": 500, "Unit_Price": 52.00, "Invoice_Date": date(2024, 3, 20), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-008", "Vendor_Name": "TechServ India", "Item_Description": "Cloud Hosting Services Monthly", "Quantity": 12, "Unit_Price": 450.00, "Invoice_Date": date(2024, 4, 1), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-009", "Vendor_Name": "TechServ India", "Item_Description": "Network Cable Cat6 100m", "Quantity": 30, "Unit_Price": 1200.00, "Invoice_Date": date(2024, 4, 15), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-010", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "A4 Copier Paper 80gsm", "Quantity": 100, "Unit_Price": 350.00, "Invoice_Date": date(2024, 5, 1), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-011", "Vendor_Name": "BuildRight Materials", "Item_Description": "Cement OPC 53 Grade", "Quantity": 200, "Unit_Price": 380.00, "Invoice_Date": date(2024, 5, 15), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-013", "Vendor_Name": "TechServ India", "Item_Description": "Cloud Hosting Services Monthly", "Quantity": 12, "Unit_Price": 450.00, "Invoice_Date": date(2024, 6, 1), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-014", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "Executive Office Desk", "Quantity": 3, "Unit_Price": 4500.00, "Invoice_Date": date(2024, 6, 15), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-016", "Vendor_Name": "BuildRight Materials", "Item_Description": "Cement OPC 53 Grade", "Quantity": 150, "Unit_Price": 380.00, "Invoice_Date": date(2024, 7, 1), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-017", "Vendor_Name": "TechServ India", "Item_Description": "Network Cable Cat6 100m", "Quantity": 15, "Unit_Price": 1200.00, "Invoice_Date": date(2024, 8, 1), "Currency": "INR"})
invoices.append({"Invoice_Number": "INV-DEMO-020", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "Printer Toner Cartridge", "Quantity": 10, "Unit_Price": 2800.00, "Invoice_Date": date(2024, 9, 1), "Currency": "INR"})

# --- 3 PRICE MISMATCH invoices ---
# INV-DEMO-004: Contract 450, Invoice 520, Qty 100 -> leakage 7,000
invoices.append({"Invoice_Number": "INV-DEMO-004", "Vendor_Name": "TechServ India", "Item_Description": "Cloud Hosting Services Monthly", "Quantity": 100, "Unit_Price": 520.00, "Invoice_Date": date(2024, 3, 15), "Currency": "INR"})
# INV-DEMO-012: Contract 52, Invoice 65, Qty 1000 -> leakage 13,000
invoices.append({"Invoice_Number": "INV-DEMO-012", "Vendor_Name": "BuildRight Materials", "Item_Description": "Steel Reinforcement Bars 12mm", "Quantity": 1000, "Unit_Price": 65.00, "Invoice_Date": date(2024, 5, 25), "Currency": "INR"})
# INV-DEMO-015: Contract 2800, Invoice 3100, Qty 25 -> leakage 7,500
invoices.append({"Invoice_Number": "INV-DEMO-015", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "Printer Toner Cartridge", "Quantity": 25, "Unit_Price": 3100.00, "Invoice_Date": date(2024, 7, 10), "Currency": "INR"})

# --- 1 QUANTITY MISMATCH invoice ---
# INV-DEMO-019: PO=50, Invoice=75, Price=800 -> leakage 20,000
invoices.append({"Invoice_Number": "INV-DEMO-019", "Vendor_Name": "BuildRight Materials", "Item_Description": "Safety Helmets Industrial Grade", "Quantity": 75, "Unit_Price": 800.00, "Invoice_Date": date(2024, 8, 10), "Currency": "INR"})

# --- 2 NEAR-DUPLICATE invoices ---
# Near-dupe for Rule 2: same vendor, same total, different invoice_no,
# within 30-day window, and shared item description.
#
# Pair 1: INV-DEMO-007 near-dupe of INV-DEMO-003 (Acme, Printer Toner, 56,000)
# NOTE: tenant duplicate_window_days=7, so date must be within 7 days of pair
invoices.append({"Invoice_Number": "INV-DEMO-007", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "Printer Toner Cartridge", "Quantity": 20, "Unit_Price": 2800.00, "Invoice_Date": date(2024, 3, 5), "Currency": "INR"})
# Pair 2: INV-DEMO-018 near-dupe of INV-DEMO-011 (BuildRight, Cement, 76,000)
invoices.append({"Invoice_Number": "INV-DEMO-018", "Vendor_Name": "BuildRight Materials", "Item_Description": "Cement OPC 53 Grade", "Quantity": 200, "Unit_Price": 380.00, "Invoice_Date": date(2024, 5, 20), "Currency": "INR"})


# ═══════════════════════════════════════════════════════
# PURCHASE ORDERS — 6 POs
# ═══════════════════════════════════════════════════════
pos = [
    {"PO_Number": "PO-DEMO-001", "Vendor_Name": "Acme Supplies Ltd", "Item_Description": "A4 Copier Paper 80gsm", "PO_Date": date(2024, 1, 25), "Ordered_Quantity": 200, "Unit": "Nos"},
    {"PO_Number": "PO-DEMO-002", "Vendor_Name": "BuildRight Materials", "Item_Description": "Safety Helmets Industrial Grade", "PO_Date": date(2024, 3, 1), "Ordered_Quantity": 50, "Unit": "Nos"},
    {"PO_Number": "PO-DEMO-003", "Vendor_Name": "BuildRight Materials", "Item_Description": "Safety Helmets Industrial Grade", "PO_Date": date(2024, 8, 1), "Ordered_Quantity": 50, "Unit": "Nos"},
    # PO-DEMO-007: must be the ONLY PO for Steel Bars — rule3 picks first exact
    # match by ID, so having a qty=500 PO before this one would cause false positives.
    {"PO_Number": "PO-DEMO-007", "Vendor_Name": "BuildRight Materials", "Item_Description": "Steel Reinforcement Bars 12mm", "PO_Date": date(2024, 5, 20), "Ordered_Quantity": 1000, "Unit": "Nos"},
    {"PO_Number": "PO-DEMO-005", "Vendor_Name": "TechServ India", "Item_Description": "Network Cable Cat6 100m", "PO_Date": date(2024, 4, 10), "Ordered_Quantity": 30, "Unit": "Nos"},
    {"PO_Number": "PO-DEMO-006", "Vendor_Name": "BuildRight Materials", "Item_Description": "Cement OPC 53 Grade", "PO_Date": date(2024, 5, 10), "Ordered_Quantity": 200, "Unit": "Nos"},
]


# ═══════════════════════════════════════════════════════
# EXPECTED OUTPUT
# ═══════════════════════════════════════════════════════
expected_output = [
    {"Rule": "PRICE_MISMATCH", "Vendor": "TechServ India", "Invoice_Number": "INV-DEMO-004", "Item": "Cloud Hosting Services Monthly", "Contract_Price": 450.00, "Invoice_Price": 520.00, "Quantity": 100, "Expected_Leakage_Amount": 7000.00, "Notes": "Contract 450/unit, invoiced 520/unit. Overcharge: 70 x 100 = 7,000"},
    {"Rule": "PRICE_MISMATCH", "Vendor": "BuildRight Materials", "Invoice_Number": "INV-DEMO-012", "Item": "Steel Reinforcement Bars 12mm", "Contract_Price": 52.00, "Invoice_Price": 65.00, "Quantity": 1000, "Expected_Leakage_Amount": 13000.00, "Notes": "Contract 52/unit, invoiced 65/unit. Overcharge: 13 x 1000 = 13,000"},
    {"Rule": "PRICE_MISMATCH", "Vendor": "Acme Supplies Ltd", "Invoice_Number": "INV-DEMO-015", "Item": "Printer Toner Cartridge", "Contract_Price": 2800.00, "Invoice_Price": 3100.00, "Quantity": 25, "Expected_Leakage_Amount": 7500.00, "Notes": "Contract 2800/unit, invoiced 3100/unit. Overcharge: 300 x 25 = 7,500"},
    {"Rule": "DUPLICATE_INVOICE", "Vendor": "Acme Supplies Ltd", "Invoice_Number": "INV-DEMO-003 / INV-DEMO-007", "Item": "Printer Toner Cartridge", "Contract_Price": None, "Invoice_Price": 2800.00, "Quantity": 20, "Expected_Leakage_Amount": 56000.00, "Notes": "Near-duplicate pair: same vendor, same amount 56,000, 4 days apart (within 7-day window), shared item desc"},
    {"Rule": "DUPLICATE_INVOICE", "Vendor": "BuildRight Materials", "Invoice_Number": "INV-DEMO-011 / INV-DEMO-018", "Item": "Cement OPC 53 Grade", "Contract_Price": None, "Invoice_Price": 380.00, "Quantity": 200, "Expected_Leakage_Amount": 76000.00, "Notes": "Near-duplicate pair: same vendor, same amount 76,000, 5 days apart (within 7-day window), shared item desc"},
    {"Rule": "QUANTITY_MISMATCH", "Vendor": "BuildRight Materials", "Invoice_Number": "INV-DEMO-019", "Item": "Safety Helmets Industrial Grade", "Contract_Price": 800.00, "Invoice_Price": 800.00, "Quantity": 75, "Expected_Leakage_Amount": 20000.00, "Notes": "PO authorized 50 units, invoice claims 75 units. Excess: 25 x 800 = 20,000"},
]


def main():
    print("=== LeakSight V1 — Demo Data Generator ===\n")

    contracts_df = pd.DataFrame(contracts)
    contracts_df.to_excel(OUTPUT_DIR / "Contracts_Demo.xlsx", index=False)
    print(f"Contracts:       {len(contracts_df)} rows -> Contracts_Demo.xlsx")

    inv_df = pd.DataFrame(invoices)
    inv_df.to_excel(OUTPUT_DIR / "Invoices_Demo.xlsx", index=False)
    print(f"Invoices:        {len(inv_df)} rows -> Invoices_Demo.xlsx")

    pos_df = pd.DataFrame(pos)
    pos_df.to_excel(OUTPUT_DIR / "PO_Demo.xlsx", index=False)
    print(f"POs:             {len(pos_df)} rows -> PO_Demo.xlsx")

    expected_df = pd.DataFrame(expected_output)
    expected_df.to_excel(OUTPUT_DIR / "Demo_Expected_Output.xlsx", index=False)
    print(f"Expected:        {len(expected_df)} rows -> Demo_Expected_Output.xlsx")

    print(f"\n=== SUMMARY ===")
    print(f"Vendors:          3")
    print(f"Contracts:        {len(contracts_df)} line items across 5 contracts")
    print(f"Invoices:         {len(inv_df)} total (14 clean + 3 price + 1 qty + 2 near-dupe)")
    print(f"POs:              {len(pos_df)}")
    print(f"\nExpected leakage: 6 findings")
    print(f"  PRICE_MISMATCH:    3 (7,000 + 13,000 + 7,500 = 27,500)")
    print(f"  DUPLICATE_INVOICE: 2 near-dupes (56,000 + 76,000 = 132,000)")
    print(f"  QUANTITY_MISMATCH: 1 (20,000)")
    total = sum(r["Expected_Leakage_Amount"] for r in expected_output)
    print(f"  TOTAL:             {total:,.2f}")
    print(f"\nAll files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
