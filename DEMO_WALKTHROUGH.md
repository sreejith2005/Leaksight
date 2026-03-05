# LeakSight V1 — Non-Builder Demo Walkthrough

**Purpose**: Step-by-step guide for observers (stakeholders, pilot testers, CFO review) who have **zero knowledge of the codebase** to walk through the complete LeakSight analysis workflow in the browser.

**Pre-requisites**:
- System running (backend, worker, frontend, database)
- Demo data already uploaded (see `_upload_demo_data.py` — 3 vendors, 20 invoices, 6 POs, 8 contracts)
- Demo analysis run complete with 6 findings (₹179,500 total leakage)

**Credentials**:
- URL: `http://localhost:5173`
- Email: `admin@test.com`
- Password: `PZAD-QyiIWCBct2iRxvEkQ`

---

## Step 1: Login

1. Open `http://localhost:5173` in Chrome/Edge
2. Enter the email and password above
3. Click **Login**
4. You should land on the **Dashboard** page

**What to observe**: Login is instant. JWT token is stored in the browser. If you see a redirect back to login, the backend may be down.

---

## Step 2: Dashboard Overview

**Route**: `/` (lands here after login)

**What you see**:
- **4 KPI cards** at the top:
  - Total Accepted Leakage — shows ₹0.00 initially (no records accepted yet)
  - Pending Review — **6** (our demo findings waiting for review)
  - Pending FX Rate — 0 (all amounts in INR, no FX conversion needed)
  - Average Confidence — ~0.93 (weighted average across all 6 findings)
- **Recent Analysis Runs table** — one row: "Demo Dataset Analysis" with status COMPLETE, 6 records

**What to observe**: The dashboard provides an at-a-glance summary. KPI values update when you accept/reject findings.

---

## Step 3: Upload Page (Read-Only Tour)

**Route**: Click **Upload** in the left sidebar

**What you see**:
- Drag-and-drop zone for file upload
- Dropdown to select document type (Invoice, Contract, Purchase Order)
- **Recent Runs** section below — shows the completed demo run

**What to observe**: This is where new documents would be uploaded in production. For this demo, data is already loaded. You can optionally upload a second batch here to see the live parsing workflow.

---

## Step 4: Leakage Review — Browse All Findings

**Route**: Click **Leakage Review** in the left sidebar

**What you see**:
A table with **6 rows** — one per leakage finding. Columns include:
| Column | Description |
|--------|-------------|
| Invoice No | e.g. INV-DEMO-004 |
| Vendor | e.g. TechServ India |
| Type | PRICE_MISMATCH, DUPLICATE_INVOICE, or QUANTITY_MISMATCH |
| Amount | Leakage amount in ₹ |
| Confidence | 0.85–1.0 |
| Status | PENDING (all start here) |

**Expected 6 findings**:

| # | Invoice | Vendor | Type | Amount (₹) | Confidence |
|---|---------|--------|------|-------------|------------|
| 1 | INV-DEMO-004 | TechServ India | PRICE_MISMATCH | 7,000 | 1.0 |
| 2 | INV-DEMO-012 | BuildRight Materials | PRICE_MISMATCH | 13,000 | 1.0 |
| 3 | INV-DEMO-015 | Acme Supplies | PRICE_MISMATCH | 7,500 | 1.0 |
| 4 | INV-DEMO-007 | Acme Supplies | DUPLICATE_INVOICE | 56,000 | 0.85 |
| 5 | INV-DEMO-018 | BuildRight Materials | DUPLICATE_INVOICE | 76,000 | 0.85 |
| 6 | INV-DEMO-019 | BuildRight Materials | QUANTITY_MISMATCH | 20,000 | 0.9 |

**Filter test**: Use the status/type dropdowns to filter by PRICE_MISMATCH only — should show 3 rows.

---

## Step 5: Leakage Detail — Review a Finding

**Route**: Click on any row in the leakage table (e.g., INV-DEMO-004)

**What you see**:
- **Invoice reference**: Invoice number, date, vendor, total amount
- **Leakage explanation**: Human-readable text explaining the mismatch
  - Example for price mismatch: "Contract rate ₹450/unit, invoiced at ₹520/unit. Overcharge: ₹70 × 100 = ₹7,000"
- **Evidence details**: Contract reference, matched item description, quantities
- **Confidence score** with visual indicator
- **Accept / Reject buttons**

### Accept/Reject Workflow:

1. Click **Accept** to confirm the finding as valid leakage
2. Click **Reject** to dismiss it — a modal appears asking for rejection notes
3. After action, status changes from PENDING → ACCEPTED or REJECTED

**Recommended demo action**: Accept all 6 findings to see the dashboard KPI update.

---

## Step 6: Accept All Findings (Interactive Demo)

Repeat for each finding:
1. Go back to **Leakage Review** (`/leakage`)
2. Click a PENDING row
3. Click **Accept**
4. Return to list

After accepting all 6:
- Go to **Dashboard** (`/`)
- **Total Accepted Leakage** should now show **₹179,500.00**
- **Pending Review** should show **0**

---

## Step 7: Vendor Management

**Route**: Click **Vendors** in the left sidebar

**What you see**:
- 3 vendors: Acme Supplies, BuildRight Materials, TechServ India
- Each shows normalized name, raw name variations, and alias count
- Click a vendor to see detail page with GST ID and alias management

**What to observe**: Vendor normalization handled automatically by the system — "Acme Supplies Ltd" in the upload normalizes to "acme supplies" for cross-document matching.

---

## Step 8: Contract Browser

**Route**: Click **Contracts** in the left sidebar

**What you see**:
- 5 contracts (CTR-DEMO-001 through CTR-DEMO-005)
- Each shows vendor, version count, validity period, and line item count
- Click a contract row to see version history

**What to observe**: Contracts serve as the price reference for Rule 1 (Price Mismatch). The system matched each invoice item against contract prices using fuzzy text matching.

---

## Step 9: Reports — Download Evidence Pack

**Route**: Click **Reports** in the left sidebar

**What you see**:
- **Run selector** dropdown — select "Demo Dataset Analysis"
- **CFO Summary section**: Total leakage, breakdown by rule type, top vendors
- **Download buttons**:
  - **Evidence Pack (PDF)** — WeasyPrint-generated executive report
  - **Excel Export** — Full findings spreadsheet

### Download test:
1. Select the demo run from the dropdown
2. Click **Download Evidence Pack (PDF)**
3. Open the downloaded file — should contain cover page, table of contents, and per-finding evidence sections
4. Click **Download Excel** — should open in Excel with all 6 findings

**Note**: PDF generation requires WeasyPrint configured in the backend. If the download fails, check backend logs.

---

## Step 10: Admin Settings

**Route**: Click **Admin** in the left sidebar

**What you see**:
- **FX Rates section**: Table of exchange rates (empty if all amounts are in INR)
- **Tenant Settings**: Base currency (INR), duplicate detection window (7 days), fuzzy matching threshold

**What to observe**: The duplicate detection window is set to 7 days — this means only invoices with matching vendor+amount within a 7-day date range are flagged as near-duplicates.

---

## Step 11: Notifications

**Route**: Click the **bell icon** in the top-right, or click **Notifications** in sidebar (if available)

**What you see**:
- Notification for "Analysis run completed" — created automatically when the demo run finished
- Mark as read capability

---

## Summary Checklist

After completing the walkthrough, verify:

- [ ] Login works, dashboard loads
- [ ] 6 leakage findings visible in Leakage Review
- [ ] Each finding has a human-readable explanation
- [ ] Accept/Reject workflow functions correctly
- [ ] Dashboard KPIs update after accepting findings
- [ ] 3 vendors visible with normalized names
- [ ] 5 contracts visible with line items
- [ ] Reports page can download PDF and Excel
- [ ] Admin page shows tenant settings
- [ ] Notifications appear for completed run

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Login fails | Backend not running | Start backend: `.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000` |
| Dashboard empty | No analysis run in DB | Run `_upload_demo_data.py` to upload demo data and trigger analysis |
| Only 0 findings | Worker not running | Start worker: `.venv\Scripts\python.exe -m celery -A backend.app.core.celery_app worker --loglevel=info --pool=solo -Q default,parse,analysis` |
| PDF download fails | WeasyPrint not installed | `pip install weasyprint` — requires system Cairo/Pango libraries |
| Page loads blank | Frontend not running | Start frontend: `cd frontend && npm run dev` |

---

## Observer Feedback Form

After completing the walkthrough, please note:

1. **Clarity** (1-5): How clear was the leakage explanation for each finding?
2. **Navigation** (1-5): How intuitive was it to move between pages?
3. **Trust** (1-5): How confident are you in the accuracy of the findings?
4. **Speed** (1-5): Was the system responsive during your session?
5. **Actionability** (1-5): Could you take action based on the report outputs?
6. **Overall** (1-5): Overall impression of the system?
7. **Comments**: Any specific issues, suggestions, or observations?
