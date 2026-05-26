"""Generate PO test data for LeakSight V1 Quantity Mismatch testing.

Reads the invoices Excel file, filters rows where Invoice_Status_Type == 'Quantity Mismatch',
and creates a PO file with ordered quantities at 70% of invoice quantities so that
invoice quantities always exceed PO quantities (triggering Rule 3).
"""
import pandas as pd
from datetime import timedelta

# Read invoices
invoices_path = r"C:\Users\LENOVO\Downloads\Sample Invoices - LeakSight MVP Testing.xlsx"
df = pd.read_excel(invoices_path)

# Filter Quantity Mismatch rows
qty_mismatch = df[df["Invoice_Status_Type"] == "Quantity Mismatch"].copy()
print(f"Found {len(qty_mismatch)} Quantity Mismatch rows")

# Build PO data
po_rows = []
for _, row in qty_mismatch.iterrows():
    inv_date = pd.to_datetime(row["Invoice_Date"])
    po_date = inv_date - timedelta(days=7)
    ordered_qty = round(row["Quantity"] * 0.7)  # 70% of invoice qty

    po_rows.append({
        "PO_Number": f"PO-{row['Invoice_Number']}",
        "Vendor_Name": row["Vendor_Name"],
        "Item_Description": row["Item_Description"],
        "PO_Date": po_date.strftime("%Y-%m-%d"),
        "Ordered_Quantity": ordered_qty,
        "Unit": row["Unit"],
        "Unit_Price": row["Unit_Price"],
    })

po_df = pd.DataFrame(po_rows)
output_path = r"C:\Users\LENOVO\Downloads\PO_Test_Data.xlsx"
po_df.to_excel(output_path, index=False)
print(f"PO test data saved to {output_path}")
print(f"Total PO rows: {len(po_df)}")
print(f"\nSample rows:")
print(po_df.head(3).to_string())
