# LeakSight V1 — Rules Engine Specification

## 1. Overview

The rules engine is the core intellectual property of LeakSight. It takes matched invoice line items and applies deterministic, explainable rules to detect financial leakage.

### Design Principles

1. **Deterministic** — Given the same inputs, the same outputs must be produced. No randomness, no ML inference, no probabilistic decisions.
2. **Explainable** — Every leakage finding must include a human-readable explanation string that a non-technical person can understand.
3. **Re-playable** — Running the same data through the same rules version must produce identical results. This is verified by the pilot readiness checklist (Section 1.1).
4. **No guessing** — The system never guesses a missing price, never guesses an FX rate, never infers a commercial term without evidence.

### V1 Rule Set (Locked)

| Rule | Name | Leakage Type | Description |
|---|---|---|---|
| Rule 1 | Invoice vs Contract Price Mismatch | `PRICE_MISMATCH` | Invoice unit price exceeds contract unit price for the same item |
| Rule 2 | Duplicate Invoice | `DUPLICATE_INVOICE` | Same invoice submitted more than once |
| Rule 3 | Quantity Mismatch | `QUANTITY_MISMATCH` | Invoice quantity exceeds received (GRN) or ordered (PO) quantity |

This set is **locked for V1**. No rules can be added, removed, or reordered during V1 implementation.

---

## 2. Rule Execution Flow

The rule engine orchestrator (`rules/rule_engine.py`) is called once per invoice line item. It runs each rule in sequence:

```
For each invoice_line_item in run:
  1. Resolve vendor match (already done in normalization phase)
  2. Run Rule 1 (Price Mismatch) → LeakageRecord | None
  3. Run Rule 2 (Duplicate Invoice) → LeakageRecord | None  [runs at invoice level, not line item]
  4. Run Rule 3 (Quantity Mismatch) → LeakageRecord | None
  5. Collect all non-None results → write to leakage_records table
```

**Important:** Rule 2 (Duplicate Invoice) operates at the **invoice header level**, not per line item. It is evaluated once per invoice, not once per line item. The rule engine handles this by tracking which invoices have already been checked for duplicates in the current run.

### What Happens When No Rule Fires

If all three rules return `None` for an invoice line item, **no leakage record is created**. This is the correct and expected behavior. Absence of leakage is not an error — it means the invoice line item is clean. No record with amount = 0 is created. No "clean" status record is written.

---

## 3. Rule 1 — Invoice vs Contract Price Mismatch

### 3.1 Purpose

Detect when a vendor charges more on an invoice than what is contractually agreed.

**Leakage Type:** `PRICE_MISMATCH`

### 3.2 Required Inputs

| Input | Source | Required |
|---|---|---|
| Invoice line item | `invoice_line_items` table | Yes |
| Invoice header | `invoices` table (for `invoice_date`, `vendor_id`, `currency`) | Yes |
| Contract version | `contract_versions` table (resolved by vendor + date) | Yes (if not found, Rule 1 skips) |
| Contract line item | `contract_line_items` table (matched by item description) | Yes (if not found, Rule 1 skips) |
| Unit conversion factor | `unit_conversion_factors` table | Only if units differ |
| FX rate | `fx_rates` table | Only if currencies differ |

### 3.3 Execution Steps

#### Step 1: Contract Validity Check

Call `core/contract_resolver.py → get_valid_contract_version(vendor_id, invoice_date, tenant_id)`.

| Result | Action |
|---|---|
| **Exactly 1 valid version** | Proceed to Step 2 |
| **0 valid versions** | **Skip Rule 1 entirely** for this invoice line item. No leakage record created. This is not an error — it means no contract covers this invoice date. |
| **>1 valid versions (overlap)** | Flag for manual review. Create leakage record with `confidence = 0.5`, `explanation = "Multiple overlapping contract versions found for vendor {vendor_name} on {invoice_date}. Manual review required to determine correct contract price."`, `status = PENDING`. |

**Critical:** The system must check the contract's `valid_from` and `valid_to` dates against the invoice's `invoice_date`. It must **never** use the "latest" contract version by default — it must use the version that was valid on the invoice date.

#### Step 2: Item Matching

Match the invoice line item's `item_desc` against contract line items in the resolved contract version.

**Matching sequence:**
1. Exact match (after normalization) → `item_match_confidence = 1.0`
2. RapidFuzz `token_sort_ratio` → `item_match_confidence = score / 100`
3. If score < `tenant.fuzzy_threshold` → no match found, **skip Rule 1** for this line item

If no matching contract line item is found, Rule 1 skips. No leakage record is created. The system does **not** guess which contract line item applies.

#### Step 3: Unit Conversion Check

Compare the invoice line item's `unit` with the matched contract line item's `unit`.

| Scenario | Action |
|---|---|
| **Same unit** | No conversion needed. Proceed to Step 4. |
| **Different unit, same dimension** | Call `core/unit_converter.py → convert_units(invoice_unit_price, invoice_unit, contract_unit, tenant_id)`. Use the converted price for comparison. Record conversion details in `evidence_jsonb.unit_conversion_details`. |
| **Different unit, different dimension** | **Skip Rule 1** for this line item. Raise an explicit warning in the run logs. Record a failure flag. This is a data quality issue, not a leakage detection scenario. The system never silently converts across dimensions (e.g., KG to Litres). |
| **Unknown unit** | **Skip Rule 1**. Flag the document for manual review. |

#### Step 4: Currency Check

Compare the invoice `currency` with the contract line item `currency`.

| Scenario | Action |
|---|---|
| **Same currency** | No conversion needed. Proceed to Step 5. |
| **Different currency** | Call `core/fx_service.py → get_rate(invoice_currency, contract_currency, invoice_date, tenant_id)`. |
| **FX rate found** | Convert invoice price to contract currency using the rate. Record rate details in `evidence_jsonb.fx_rate_applied`. Proceed to Step 5. |
| **FX rate NOT found** | **Create a leakage record with status `PENDING_FX_RATE`**. Set `amount = 0`. Populate all evidence fields except the final calculation. Set `explanation = "Price mismatch suspected but FX rate for {from_currency} to {to_currency} on {invoice_date} is not available. Upload the FX rate to complete this calculation."` The system **never** uses a rate from a different date as a proxy. It **never** guesses an FX rate. |

**PENDING_FX_RATE Conditions (Explicit):**
- Invoice currency ≠ contract currency
- No FX rate exists in the `fx_rates` table for `(from_currency, to_currency)` with `rate_date <= invoice_date`
- The record is created, not skipped — this ensures it surfaces for admin action
- Once an admin uploads the missing FX rate, the analysis can be re-triggered and the PENDING_FX_RATE records will resolve

#### Step 5: Price Comparison

After unit conversion (if needed) and currency conversion (if needed):

```python
price_difference = invoice_unit_price_converted - contract_unit_price
```

| Result | Action |
|---|---|
| `price_difference > 0` | **Leakage detected.** Calculate `total_leakage = price_difference × quantity`. Create leakage record. |
| `price_difference <= 0` | **No leakage.** Invoice price is at or below contract price. Return `None`. No record created. |

#### Step 6: Confidence Calculation

The confidence score for a Rule 1 finding is the **minimum** of the component confidence scores:

```python
confidence = min(
    vendor_match_confidence,    # From vendor matching (1.0 for GST/alias, fuzzy score otherwise)
    item_match_confidence,      # From item matching (1.0 for exact, fuzzy score otherwise)
)
```

- If both vendor and item were exact matches: `confidence = 1.0`
- If vendor was alias match (1.0) and item was fuzzy (0.92): `confidence = 0.92`
- A `confidence = 1.0` should **only** appear for GST exact + exact item match, or alias match + exact item match.

If unit conversion was applied, confidence is **not reduced** (unit conversion factors are deterministic, not probabilistic). If FX conversion was applied, confidence is **not reduced** (FX rates are exact values from a reference source, not estimates).

#### Step 7: Evidence Population

Populate `evidence_jsonb` with:
- `invoice_reference` — all invoice line item details
- `contract_reference` — all contract line item details, version number, validity dates
- `calculation` — price difference per unit, quantity, total leakage, currency
- `unit_conversion_details` — whether conversion was applied, from/to units, factor, source
- `fx_rate_applied` — whether FX conversion was needed, rate, rate date, source
- `match_confidence_breakdown` — vendor match method/confidence, item match method/confidence, overall
- `source_documents` — both invoice and contract document IDs, filenames, hashes

#### Step 8: Human-Readable Explanation

Generate an explanation string following this template:

**Standard case (no conversion):**
```
"Invoice {invoice_no} from {vendor_name} charges ₹{invoice_price}/unit for '{item_desc}' but the contract (version {version_number}, valid {valid_from} to {valid_to}) specifies ₹{contract_price}/unit. Overcharge of ₹{price_diff}/unit × {quantity} units = ₹{total_leakage} total."
```

**With unit conversion:**
```
"Invoice {invoice_no} from {vendor_name} charges ₹{invoice_price}/{invoice_unit} for '{item_desc}'. After converting to {contract_unit} (factor: {factor}), this equals ₹{converted_price}/{contract_unit}. The contract (version {version_number}, valid {valid_from} to {valid_to}) specifies ₹{contract_price}/{contract_unit}. Overcharge of ₹{price_diff}/{contract_unit} × {quantity} {contract_unit} = ₹{total_leakage} total."
```

**With FX conversion:**
```
"Invoice {invoice_no} from {vendor_name} charges {invoice_currency} {invoice_price}/unit for '{item_desc}'. Using FX rate {rate} ({rate_source}, {rate_date}), this equals ₹{converted_price}/unit. The contract specifies ₹{contract_price}/unit. Overcharge of ₹{price_diff}/unit × {quantity} units = ₹{total_leakage} total."
```

### 3.4 Partial Match Handling

A "partial match" occurs when:
- Vendor matched via fuzzy matching (not GST exact or alias)
- Item matched via fuzzy matching (not exact)
- Confidence < 1.0

**Partial match behavior:**
- The leakage record is still created
- Confidence reflects the match quality (typically 0.70–0.99)
- The record goes into the review queue with status `PENDING`
- The explanation string must indicate the match was fuzzy: append `"(vendor matched by name similarity at {confidence}%)"` or `"(item matched by description similarity at {confidence}%)"`
- The reviewer can accept or reject based on the evidence

### 3.5 PARTIAL_SUCCESS Conditions for Rule 1

A run transitions to `PARTIAL_SUCCESS` if any of the following occurred during Rule 1 processing:
- One or more PENDING_FX_RATE records were created
- One or more invoice line items had cross-dimension unit mismatches (flagged, skipped)
- One or more contract version overlaps required manual review

---

## 4. Rule 2 — Duplicate Invoice

### 4.1 Purpose

Detect when the same invoice is submitted more than once — either exactly or near-identically.

**Leakage Type:** `DUPLICATE_INVOICE`

### 4.2 Important: Invoice-Level Rule

Unlike Rules 1 and 3, Rule 2 operates at the **invoice header level**. It checks whether an entire invoice is a duplicate, not individual line items. In the rule engine orchestrator, Rule 2 is called once per invoice, not once per line item.

### 4.3 Exact Duplicate Definition

An exact duplicate exists when:

```
invoice_a.invoice_no = invoice_b.invoice_no
AND invoice_a.vendor_id = invoice_b.vendor_id
AND invoice_a.tenant_id = invoice_b.tenant_id
AND invoice_a.id ≠ invoice_b.id    (not comparing to itself)
```

This is enforced at the database level by the unique constraint `(tenant_id, invoice_no)`. If an invoice with the same number from the same vendor is uploaded, the system will either:
- **Reject the insert** (if the constraint is enforced on upload) — in which case Rule 2 flags the attempt
- **Detect the existing match** during analysis — query for existing invoices with the same `invoice_no` and `vendor_id`

**Exact duplicate confidence:** `1.0`

### 4.4 Near-Duplicate Definition

A near-duplicate exists when:

```
invoice_a.vendor_id = invoice_b.vendor_id
AND invoice_a.total_amount = invoice_b.total_amount
AND invoice_a.tenant_id = invoice_b.tenant_id
AND ABS(invoice_a.invoice_date - invoice_b.invoice_date) <= tenant.duplicate_window_days
AND invoice_a.id ≠ invoice_b.id
AND invoice_a.invoice_no ≠ invoice_b.invoice_no    (different invoice numbers)
```

**The query that detects near-duplicates uses the composite index `(tenant_id, vendor_id, invoice_date)`** created in Phase 2.5:

```sql
SELECT i2.* FROM invoices i2
WHERE i2.tenant_id = :tenant_id
  AND i2.vendor_id = :vendor_id
  AND i2.total_amount = :total_amount
  AND i2.invoice_date BETWEEN :date_start AND :date_end
  AND i2.id != :current_invoice_id
  AND i2.invoice_no != :current_invoice_no;
```

Where:
- `:date_start = invoice_date - duplicate_window_days`
- `:date_end = invoice_date + duplicate_window_days`

This query is efficient because the composite index allows PostgreSQL to seek by `(tenant_id, vendor_id)` and then range scan on `invoice_date`.

**Near-duplicate confidence:** `0.85` (configurable — this reflects the uncertainty that two invoices with the same amount from the same vendor in the same window might be legitimately different invoices)

### 4.5 Window Configuration

The `duplicate_window_days` value is stored in `tenant_settings.duplicate_window_days`. Default: `30` days.

This means a near-duplicate is flagged if two invoices from the same vendor, with the same amount, fall within 30 days of each other (configurable per tenant).

### 4.6 Execution Steps

#### Step 1: Check for Exact Duplicates

Query `invoices` for matching `invoice_no` + `vendor_id` + `tenant_id` (excluding current invoice).

| Result | Action |
|---|---|
| **Match found** | Create leakage record. `amount = invoice.total_amount` (the full invoice amount, since the entire invoice is duplicate). `confidence = 1.0`. |
| **No match** | Proceed to Step 2. |

#### Step 2: Check for Near-Duplicates

Query `invoices` using the composite-index-optimized query above.

| Result | Action |
|---|---|
| **One or more matches found** | Create leakage record for each match pair. `amount = invoice.total_amount`. `confidence = 0.85`. |
| **No matches** | Rule 2 returns `None`. No duplicate detected. |

#### Step 3: Evidence Population

For both exact and near-duplicate findings:

```json
{
  "duplicate_reference": {
    "original_invoice_id": "uuid-of-the-other-invoice",
    "original_invoice_no": "INV-2024-001",
    "duplicate_type": "EXACT" | "NEAR_DUPLICATE",
    "temporal_distance_days": 15
  }
}
```

Also populate:
- `invoice_reference` — full details of the current (flagged) invoice
- `source_documents` — document IDs of both invoices

#### Step 4: Human-Readable Explanation

**Exact duplicate:**
```
"Invoice {invoice_no} from {vendor_name} for ₹{amount} appears to be an exact duplicate of a previously uploaded invoice (same invoice number, same vendor). Total duplicate amount: ₹{amount}."
```

**Near-duplicate:**
```
"Invoice {invoice_no} from {vendor_name} for ₹{amount} dated {date_a} may be a duplicate of Invoice {other_invoice_no} for ₹{amount} dated {date_b} ({distance} days apart). Same vendor, same amount, within the {window}-day duplicate detection window."
```

### 4.7 What Rule 2 Does NOT Flag

- Two invoices from the **same vendor** with **different amounts** → NOT a duplicate
- Two invoices with the **same amount** from **different vendors** → NOT a duplicate
- Two invoices from the **same vendor** with the **same amount** but **outside** `duplicate_window_days` → NOT a duplicate
- An invoice compared against itself → NOT a duplicate (filtered by `id != current_id`)

---

## 5. Rule 3 — Quantity Mismatch

### 5.1 Purpose

Detect when an invoice claims a higher quantity than what was actually received (GRN) or ordered (PO).

**Leakage Type:** `QUANTITY_MISMATCH`

### 5.2 Authority Hierarchy

**GRN overrides PO.** GRN reflects reality (what was actually received). PO reflects intent (what was ordered). If both exist, GRN is the authority.

```
GRN > PO > Nothing
```

### 5.3 Required Inputs

| Input | Source | Required |
|---|---|---|
| Invoice line item | `invoice_line_items` table | Yes |
| GRN line item | `grn_line_items` table (matched by item description) | Optional |
| PO line item | `po_line_items` table (matched by item description) | Optional |

### 5.4 Execution Steps

#### Step 1: Find Matching GRN

For the current invoice's vendor and item description, look for a matching GRN line item:

1. Find GRNs linked to POs from the same vendor (`grns.po_id → purchase_orders.vendor_id = invoice.vendor_id`)
2. Within those GRNs, find a GRN line item whose `item_desc` matches the invoice line item's `item_desc` (exact match first, then fuzzy with `token_sort_ratio >= tenant.fuzzy_threshold`)

#### Step 2: Determine Authority

| GRN Found? | PO Found? | Authority | Action |
|---|---|---|---|
| Yes | (irrelevant) | GRN `received_qty` | Compare invoice qty vs GRN qty |
| No | Yes | PO `ordered_qty` | Compare invoice qty vs PO qty |
| No | No | None | **Skip Rule 3 entirely.** No leakage record created. No false positive. |

#### Step 3: Quantity Comparison (GRN Override Logic)

When GRN is the authority:

```python
quantity_difference = invoice_line_item.quantity - grn_line_item.received_qty
```

| Result | Action |
|---|---|
| `quantity_difference > 0` | **Leakage detected.** Invoice claims more units than were received. |
| `quantity_difference <= 0` | **No leakage.** Invoice quantity is at or below received quantity. Return `None`. |

When PO is the authority (PO Fallback Logic):

```python
quantity_difference = invoice_line_item.quantity - po_line_item.ordered_qty
```

| Result | Action |
|---|---|
| `quantity_difference > 0` | **Leakage detected.** Invoice claims more units than were ordered. |
| `quantity_difference <= 0` | **No leakage.** Return `None`. |

#### Step 4: Leakage Amount Calculation

```python
leakage_amount = quantity_difference × invoice_line_item.unit_price
```

The leakage amount represents the financial impact of the over-claimed quantity at the invoiced unit price.

#### Step 5: Confidence Calculation

| Scenario | Confidence |
|---|---|
| GRN authority + exact item match | `1.0` |
| GRN authority + fuzzy item match | `item_match_confidence` (from fuzzy score) |
| PO authority + exact item match | `0.90` (PO is less authoritative than GRN; slightly discounted) |
| PO authority + fuzzy item match | `min(0.90, item_match_confidence)` |

#### Step 6: Evidence Population

```json
{
  "quantity_reference": {
    "po_id": "uuid-or-null",
    "po_quantity": 100.0,
    "grn_id": "uuid-or-null",
    "grn_quantity": 80.0,
    "invoiced_quantity": 100.0,
    "authority_used": "GRN",
    "quantity_difference": 20.0
  }
}
```

Also populate:
- `invoice_reference` — full invoice line item details
- `source_documents` — invoice document ID, GRN/PO document IDs
- `calculation` — `quantity_difference × unit_price = leakage_amount`
- `match_confidence_breakdown` — item match method and confidence

#### Step 7: Human-Readable Explanation

**GRN authority:**
```
"Invoice {invoice_no} from {vendor_name} claims {invoice_qty} {unit} of '{item_desc}' but the GRN (received on {grn_date}) records only {grn_qty} {unit} received. Over-invoiced by {diff} {unit} × ₹{unit_price} = ₹{leakage_amount}."
```

**PO authority (no GRN):**
```
"Invoice {invoice_no} from {vendor_name} claims {invoice_qty} {unit} of '{item_desc}' but the PO ({po_no}) only authorized {po_qty} {unit}. No GRN available to confirm receipt. Over-invoiced by {diff} {unit} × ₹{unit_price} = ₹{leakage_amount}. Note: PO used as authority because no GRN found."
```

### 5.5 Missing Document Handling

| Scenario | Behavior |
|---|---|
| Invoice exists, GRN exists, PO exists | Use GRN as authority (GRN overrides PO) |
| Invoice exists, GRN exists, PO missing | Use GRN as authority |
| Invoice exists, GRN missing, PO exists | Use PO as fallback authority |
| Invoice exists, GRN missing, PO missing | **Skip Rule 3 entirely.** Do not flag. No false positive. |

---

## 6. Confidence Scoring Summary

### 6.1 Per-Rule Confidence

| Rule | Scenario | Confidence | Rationale |
|---|---|---|---|
| **Rule 1** | GST vendor match + exact item match | `1.0` | Deterministic identifiers on both sides |
| **Rule 1** | Alias vendor match + exact item match | `1.0` | Alias is human-verified mapping |
| **Rule 1** | Alias vendor match + fuzzy item match (score 0.92) | `0.92` | Item match introduces uncertainty |
| **Rule 1** | Fuzzy vendor match (0.88) + fuzzy item match (0.92) | `0.88` | Minimum of both — weakest link |
| **Rule 1** | Overlapping contract versions | `0.50` | Ambiguous which contract applies |
| **Rule 1** | PENDING_FX_RATE | N/A (amount = 0) | Cannot calculate until rate uploaded |
| **Rule 2** | Exact duplicate | `1.0` | Same invoice number, same vendor |
| **Rule 2** | Near-duplicate | `0.85` | Heuristic — same amount + vendor + window |
| **Rule 3** | GRN authority + exact match | `1.0` | Receipt record is definitive |
| **Rule 3** | GRN authority + fuzzy match | fuzzy score | Item match introduces uncertainty |
| **Rule 3** | PO authority + exact match | `0.90` | PO is intent, not confirmed receipt |
| **Rule 3** | PO authority + fuzzy match | `min(0.90, fuzzy score)` | Both factors introduce uncertainty |

### 6.2 Confidence Threshold for Auto-Review

In V1, **all leakage records require human review**. There is no auto-acceptance based on confidence. However, the confidence score determines **sort order** in the review queue — high-confidence records appear first, guiding the reviewer toward the most defensible findings.

A `confidence = 1.0` means: "This finding is based on deterministic identifiers (GST ID, exact match, alias) and the calculation is mathematically certain."

A `confidence < 1.0` means: "This finding involves fuzzy matching — the reviewer should verify the vendor/item identification before accepting."

---

## 7. Human-Readable Explanation Requirements

### 7.1 What Makes a Valid Explanation

Every leakage record **must** have a non-null, non-empty `explanation` string. The explanation must satisfy these criteria:

1. **Readable by a non-technical person** — CFOs, auditors, and finance managers must understand it without engineering context.
2. **Self-contained** — The explanation alone must convey what was found and why, without requiring the reviewer to look up additional data.
3. **Specific** — Must reference concrete values: vendor name, invoice number, amounts, dates, quantities.
4. **Honest about uncertainty** — If fuzzy matching was used, the explanation must say so. If PO was used instead of GRN, the explanation must say so.

### 7.2 Explanation Templates by Rule

See the templates defined in each rule section above (Sections 3.8, 4.6 Step 4, 5.4 Step 7).

### 7.3 Validation

Before writing any leakage record to the database, validate:
- `explanation` is not None
- `explanation` is not an empty string
- `explanation` length > 20 characters (a meaningful explanation cannot be shorter)
- `explanation` contains at least one currency symbol or amount (it must reference financial values)

If validation fails, the leakage record must **not be created**. This is a hard rule — if a leakage cannot be explained in plain English, it must not exist.

---

## 8. Edge Cases and Boundary Conditions

### 8.1 Invoice with No Matching Contract
- Rule 1 skips. No leakage record created. This is correct — you cannot determine price overcharge without a contract baseline.

### 8.2 Invoice with Multiple Matching Contract Line Items
- If item fuzzy matching returns multiple candidates above `fuzzy_threshold`, use the **highest-scoring match only**. Record the match confidence in evidence.

### 8.3 Invoice Line Item with Zero Quantity
- Skip all rules for this line item. A zero-quantity line item is either a formatting artifact or a credit note — neither should generate leakage.

### 8.4 Invoice Line Item with Negative Amount
- Skip all rules. Negative amounts indicate credit notes or adjustments, not leakage.

### 8.5 Contract with Zero Unit Price
- Skip Rule 1 for this line item. A zero contract price is a data quality issue, not a leakage opportunity. Flag for manual review.

### 8.6 Cross-Dimension Unit Mismatch
- Explicitly raise a warning. Do not silently skip. Do not attempt conversion. Log the mismatch for review.

### 8.7 Same Invoice Uploaded Twice (Re-upload)
- The ingestion layer creates a new `raw_version` row. The canonical layer updates (not duplicates) the invoice record. Rule 2 should not flag this as a duplicate because the `invoice_no` + `vendor_id` unique constraint prevents two canonical invoice records with the same number from the same vendor.

### 8.8 Vendor Matched but Below Fuzzy Threshold
- If vendor matching returns `confidence < tenant.fuzzy_threshold`, the match is `NO_MATCH`. All three rules skip for this invoice. The invoice is flagged for manual vendor resolution.
