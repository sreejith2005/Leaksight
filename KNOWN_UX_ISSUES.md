# LeakSight V1 — Known UX Issues

**Last updated**: 2026-03-04 (Pre-Pilot)

This document tracks known UX limitations for transparency during pilot testing. None are blockers for the pilot demo, but they should be addressed before GA.

---

## P1 — Should Fix Before Pilot Go-Live

### 1. No 404 / Catch-All Route
- **Where**: Any non-existent URL path (e.g., `/foo`)
- **Behavior**: Renders the layout sidebar with blank content area
- **Expected**: Should show a "Page Not Found" message with link back to Dashboard
- **Impact**: Low — users are unlikely to type URLs manually

### 2. Currency Display Defaults to USD
- **Where**: `formatCurrency()` utility across multiple pages
- **Behavior**: Falls back to `'USD'` when a record's currency field is missing
- **Expected**: Should fall back to the tenant's base currency (INR)
- **Impact**: Medium — could confuse users if a record renders as "$7,000" instead of "₹7,000"

---

## P2 — Acceptable for Pilot, Fix Before GA

### 3. PENDING_FX_RATE Records Cannot Be Reviewed
- **Where**: Leakage Detail page (`/leakage/:id`)
- **Behavior**: Accept/Reject buttons are hidden when status is `PENDING_FX_RATE`
- **Expected**: Correct behavior — records need FX rate resolution first
- **Impact**: None for INR-only demo. Would affect multi-currency scenarios.
- **Note**: This is marked NON-NEGOTIABLE in code and is by design.

### 4. Dashboard Shows Latest Run Only
- **Where**: Dashboard KPI cards
- **Behavior**: Total Accepted Leakage and other KPIs reflect only the most recent analysis run
- **Expected**: Future: aggregate view across all runs, or a run selector
- **Impact**: Low for single-run pilot; would matter for ongoing production use

### 5. No Pagination on Notifications
- **Where**: Notifications page (`/notifications`)
- **Behavior**: Hardcoded to fetch 50 notifications max
- **Expected**: Should paginate for users with many runs
- **Impact**: None for pilot (only 1-2 runs)

### 6. Admin Page No Route Guard
- **Where**: `/admin` route
- **Behavior**: Any logged-in user can navigate to `/admin`; the page itself checks role and shows "Access Denied" inline
- **Expected**: Router-level guard should reject non-admin users before rendering
- **Impact**: Low — functional but not best practice

### 7. Reports Run Selector Limited to 20 Runs
- **Where**: Reports page (`/reports`)
- **Behavior**: Only the 20 most recent completed runs are shown in the dropdown
- **Expected**: Should paginate or have search
- **Impact**: None for pilot (single run)

### 8. Progress Percentage Can Exceed 100%
- **Where**: Run status polling (upload page + API)
- **Behavior**: `progress_percentage` shows 666.7% because `total_documents=3` but `processed_documents=20` (invoices, not documents)
- **Expected**: Progress calculation should use invoice count or be capped at 100%
- **Impact**: Cosmetic only — does not affect functionality

---

## P3 — Future Enhancement

### 9. No Real-Time Updates (WebSocket/SSE)
- **Where**: Upload page, Dashboard
- **Behavior**: Polling with 3-second intervals; NotificationsPage polls every 30 seconds
- **Expected**: Real-time push updates would improve UX
- **Impact**: Out of scope for V1 (per architecture doc)

### 10. No Direct ERP Integration
- **Where**: System-wide
- **Behavior**: All documents uploaded manually via drag-and-drop
- **Expected**: Future: SFTP/API integration with ERP systems
- **Impact**: Out of scope for V1

---

## How to Use This Document

During the pilot demo, if an observer notices any issue:
1. Check this list first — it may already be documented
2. If it's a new issue, add it below with severity (P1/P2/P3)
3. Note the page, expected behavior, and actual behavior

### Pilot-Discovered Issues

| # | Severity | Page | Description | Status |
|---|----------|------|-------------|--------|
| | | | *(add new issues here during pilot)* | |
