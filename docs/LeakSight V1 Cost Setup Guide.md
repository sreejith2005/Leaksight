# LeakSight V1 — Complete Cost, Setup & Zero-Spend Development Guide

## Executive Summary

LeakSight V1 can be built, tested, and validated entirely on a local laptop at **₹0 cost** using free, open-source tools. Every component in the tech stack — PostgreSQL, Redis, FastAPI, Celery, PaddleOCR, RapidFuzz, WeasyPrint, pdfplumber, camelot — runs locally via Docker or Python virtual environments. Production hosting only becomes necessary once a paying client is secured, at which point total monthly operating cost ranges from **₹1,600–₹3,200/month** on Hetzner Cloud.[^1][^2]

***

## Part 1: Total Cost Breakdown

### Development Phase (₹0)

During development and testing, every tool runs locally on a laptop/desktop. No server, no cloud, no payments.

| Component | Cost | Why Free |
|-----------|------|----------|
| Python 3.11+ | ₹0 | Open-source |
| FastAPI | ₹0 | Open-source Python framework |
| PostgreSQL 15 | ₹0 | Runs in Docker locally |
| Redis 7 | ₹0 | Runs in Docker locally |
| Celery | ₹0 | Open-source task queue |
| PaddleOCR + PP-Structure | ₹0 | Open-source OCR by Baidu[^3] |
| pdfplumber | ₹0 | Open-source PDF parser[^4] |
| camelot-py | ₹0 | Open-source table extractor[^5] |
| RapidFuzz | ₹0 | Open-source fuzzy matching |
| WeasyPrint | ₹0 | Open-source PDF renderer[^6] |
| React + TypeScript | ₹0 | Open-source frontend |
| TanStack Query/Table | ₹0 | Open-source |
| Docker + Docker Compose | ₹0 | Free for personal/small team use |
| Nginx | ₹0 | Open-source reverse proxy |
| Alembic | ₹0 | Open-source DB migrations |
| openpyxl / pandas | ₹0 | Open-source |
| python-docx | ₹0 | Open-source |

**Total development cost: ₹0**

### Production Phase (Post-Client)

These costs kick in **only when a paying client is secured** and the product needs to be accessible over the internet.

| Item | Monthly Cost (INR) | Notes |
|------|-------------------|-------|
| Hetzner CX41 (4 vCPU, 16 GB RAM) | ~₹1,600 (~€18.92) | Sufficient for 1–2 pilot clients[^2] |
| Hetzner CX51 (8 vCPU, 32 GB RAM) | ~₹3,000 (~€35.58) | If workload is heavier[^2] |
| Encrypted Volume (50 GB) | ~₹350 | For document + DB storage |
| Domain (.com) | ~₹800–950/year | One-time annual cost[^7][^8] |
| Domain (.in or .co.in) | ~₹400–500/year | Cheaper Indian option[^7] |
| SSL/TLS Certificate | ₹0 | Let's Encrypt is completely free[^9][^10] |
| Cloudflare DNS + CDN + DDoS | ₹0 | Free tier covers all V1 needs[^11][^12] |
| SMTP (Email notifications) | ₹0 | Brevo free: 300 emails/day (~9,000/month)[^13][^14] |
| Docker Hub | ₹0 | Not needed; images transferred via tar files |
| Monitoring | ₹0 | Cron scripts + Docker healthchecks |

### Realistic Monthly Budget

| Scenario | Monthly Cost |
|----------|-------------|
| **Development + Testing** | ₹0 |
| **First pilot client (CX41)** | ~₹1,600–2,000/month |
| **Scaling to 3–5 clients (CX51)** | ~₹3,000–3,500/month |
| **Annual domain** | ₹500–950/year (one-time) |

The key insight: the entire LeakSight tech stack is open-source. The only real recurring cost is the server, and that only starts when revenue starts.

***

## Part 2: Free Local Development Setup (Zero Cost Testing)

This section explains how to build and test the complete LeakSight MVP on a local machine without paying for anything.

### Prerequisites (What Your Laptop Needs)

- **RAM**: 8 GB minimum (16 GB recommended for PaddleOCR)
- **Disk**: 20 GB free space
- **OS**: macOS, Ubuntu/Debian Linux, or Windows with WSL2
- **Internet**: Only needed for initial downloads; all processing runs locally

### Step 1: Install Python 3.11+

**macOS:**
```bash
brew install python@3.11
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
```

**Windows (WSL2 recommended):**
Install WSL2 from Microsoft Store, then follow Ubuntu steps.

**Verify:**
```bash
python3.11 --version
```

### Step 2: Install Docker Desktop (Free)

Docker runs PostgreSQL, Redis, and all services locally in containers — no cloud needed.

**macOS / Windows:**
Download Docker Desktop from https://www.docker.com/products/docker-desktop/ (free for personal use and small businesses).

**Ubuntu:**
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

Log out and back in, then verify:
```bash
docker --version
docker compose version
```

### Step 3: Install Node.js 18+ (For React Frontend)

**macOS:**
```bash
brew install node@18
```

**Ubuntu:**
```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
```

**Verify:**
```bash
node --version
npm --version
```

### Step 4: Create Project & Python Virtual Environment

```bash
mkdir -p ~/leaksight && cd ~/leaksight
python3.11 -m venv venv
source venv/bin/activate
```

The virtual environment isolates all Python packages from your system. Always activate it before working on LeakSight.

### Step 5: Install All Python Dependencies

Create a file called `requirements.txt`:

```text
# Backend framework
fastapi==0.110.0
uvicorn[standard]==0.27.1
pydantic[email]==2.6.1
pydantic-settings==2.1.0

# Database
sqlalchemy[asyncio]==2.0.27
asyncpg==0.29.0
alembic==1.13.1

# Task queue
celery==5.3.6
redis==5.0.1

# Parsing - PDF
pdfplumber==0.11.0
camelot-py[base]==1.0.0

# Parsing - Excel/CSV
pandas==2.2.0
openpyxl==3.1.2

# Parsing - Word
python-docx==1.1.0

# Parsing - Scanned PDFs (OCR)
paddlepaddle==3.2.0
paddleocr==2.9.0

# Matching
rapidfuzz==3.6.1

# Reporting
WeasyPrint==62.0
Jinja2==3.1.3

# Security
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9

# Utilities
httpx==0.27.0
```

Install everything:

```bash
pip install -r requirements.txt
```

**Special notes for specific tools:**

**WeasyPrint** needs system-level libraries on Linux:[^15]
```bash
# Ubuntu/Debian only
sudo apt install build-essential python3-dev python3-cffi libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
```

On macOS:[^6]
```bash
brew install cairo pango gdk-pixbuf libffi
```

**PaddleOCR** — for CPU-only (no GPU needed for development):[^3][^16]
```bash
# The paddlepaddle and paddleocr lines in requirements.txt handle this
# If you have issues, install explicitly:
python -m pip install paddlepaddle==3.2.0
python -m pip install "paddleocr[all]"
```

**camelot-py** — the `[base]` extra installs necessary image backends:[^5]
```bash
pip install "camelot-py[base]"
```

### Step 6: Local Docker Compose for PostgreSQL + Redis

Create `docker-compose.dev.yml` in your project root:

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: leaksight_dev
      POSTGRES_USER: leaksight_user
      POSTGRES_PASSWORD: devpassword123
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

Start them:
```bash
docker compose -f docker-compose.dev.yml up -d
```

**Verify PostgreSQL:**
```bash
docker exec -it leaksight-postgres-1 psql -U leaksight_user -d leaksight_dev -c "SELECT version();"
```

**Verify Redis:**
```bash
docker exec -it leaksight-redis-1 redis-cli ping
# Should respond: PONG
```

These run entirely on your laptop. No internet, no cloud, no cost.

### Step 7: Initialize Database with Alembic

```bash
cd ~/leaksight
alembic init alembic
```

Configure `alembic.ini` — change the `sqlalchemy.url` line to:
```
sqlalchemy.url = postgresql://leaksight_user:devpassword123@localhost:5432/leaksight_dev
```

After writing your SQLAlchemy models (Phase 2 of the Build Order), run:
```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

### Step 8: Run FastAPI Locally

```bash
cd ~/leaksight
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` in your browser — this shows the auto-generated API documentation. FastAPI gives you this for free.

### Step 9: Run Celery Worker Locally

Open a **second terminal** (keep FastAPI running in the first):

```bash
cd ~/leaksight
source venv/bin/activate
celery -A app.core.celery_app worker --loglevel=info --concurrency=2
```

The worker processes parsing and analysis tasks in the background, using the local Redis as its message broker.

### Step 10: Run React Frontend Locally

Open a **third terminal**:

```bash
cd ~/leaksight/frontend
npm install
npm.cmd run dev
```

The frontend will be available at `http://localhost:5173` (Vite default) or `http://localhost:3000`.

### What the Local Setup Looks Like Running

```
Terminal 1: uvicorn (FastAPI backend)     → http://localhost:8000
Terminal 2: celery worker                 → processes background tasks
Terminal 3: npm.cmd run dev (React frontend)  → http://localhost:5173
Docker:     postgres + redis              → running in background
```

All of this is on your laptop. Zero cost. You can upload test invoices, parse them, run analysis, review leakage, generate reports — the full V1 workflow — without spending a single rupee.

***

## Part 3: Tool-by-Tool Setup Guide

This section explains what each tool does, why it is in the stack, and how to verify it works.

### PostgreSQL 15 (Database)

**What it does**: Stores all LeakSight data — documents, vendors, contracts, invoices, leakage records.

**Why this**: Supports Row-Level Security (RLS) for tenant isolation, JSONB for evidence storage, and is battle-tested for financial data.

**How to verify it works:**
```bash
# Connect to your local instance
docker exec -it leaksight-postgres-1 psql -U leaksight_user -d leaksight_dev

# Inside psql:
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
SELECT uuid_generate_v4();  -- Should return a UUID
\q
```

### Redis 7 (Message Broker + Cache)

**What it does**: Celery uses Redis to queue tasks (parse document, run analysis). Redis acts as the middleman between the API and the worker.

**Why this**: Lightweight, fast, simple. No need for RabbitMQ complexity in V1.

**How to verify:**
```bash
docker exec -it leaksight-redis-1 redis-cli
> SET test "hello"
> GET test
# Should return "hello"
> DEL test
> quit
```

### FastAPI (Backend Web Framework)

**What it does**: Handles all API requests — file uploads, triggering analysis runs, returning leakage records, generating reports.

**Why this**: Async support, auto-generated docs, Pydantic validation, fast.

**How to verify:**
```bash
uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000/docs in browser
# You should see the Swagger UI with all endpoints
```

### Celery (Background Task Queue)

**What it does**: Runs heavy work (parsing documents, running rules, generating reports) in the background so the API stays responsive.

**Why this**: Industry-standard Python task queue. Works with Redis out of the box.

**How to verify:**
```bash
celery -A app.core.celery_app worker --loglevel=info
# Should print: "celery@hostname ready" and list registered tasks
```

### pdfplumber (Digital PDF Parser)

**What it does**: Extracts text and tables from digital (text-based) PDFs — invoices, contracts, POs.[^4][^17]

**Why this**: Best Python library for structured text extraction from clean PDFs.

**How to verify:**
```python
import pdfplumber

with pdfplumber.open("sample_invoice.pdf") as pdf:
    page = pdf.pages
    text = page.extract_text()
    tables = page.extract_tables()
    print(text[:200])
    print(f"Found {len(tables)} tables")
```

### camelot-py (Complex Table Extractor)

**What it does**: Extracts complex multi-column, multi-page tables from PDFs that pdfplumber might struggle with.[^5]

**Why this**: Handles messy table structures (merged cells, multi-line rows) better than alternatives.

**How to verify:**
```python
import camelot

tables = camelot.read_pdf("sample_contract.pdf", pages="1-3")
print(f"Found {len(tables)} tables")
if len(tables) > 0:
    print(tables.df.head())
```

### PaddleOCR + PP-Structure (Scanned PDF OCR)

**What it does**: Reads text from scanned/image-based PDFs using optical character recognition. PP-Structure detects table layouts in scanned documents.[^16][^3]

**Why this**: Better accuracy than Tesseract (especially for Indian documents), handles table structure detection, fully open-source.

**How to verify:**
```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=True, lang='en')
result = ocr.ocr("scanned_invoice.png", cls=True)

for line in result:
    text = line[^1]
    confidence = line[^1][^1]
    print(f"{text} (confidence: {confidence:.2f})")
```

**First run will download models (~200 MB). This is a one-time download.**

### RapidFuzz (Fuzzy Matching)

**What it does**: Matches vendor names and item descriptions that are similar but not identical (e.g., "Tata Steel Pvt Ltd" vs "TATA STEEL LIMITED").

**Why this**: Fast (C++ core), deterministic, no ML/embeddings needed.

**How to verify:**
```python
from rapidfuzz import fuzz

score = fuzz.token_sort_ratio("Tata Steel Pvt Ltd", "TATA STEEL LIMITED")
print(f"Match score: {score}")  # Should be high (>80)

score2 = fuzz.token_sort_ratio("Tata Steel", "Reliance Industries")
print(f"Non-match score: {score2}")  # Should be low (<50)
```

### WeasyPrint (PDF Report Generator)

**What it does**: Takes HTML templates (Jinja2) and converts them to PDF — CFO summary reports, evidence packs.[^18][^6]

**Why this**: HTML-to-PDF with CSS support. Design reports in HTML, render as PDF.

**How to verify:**
```python
from weasyprint import HTML

html_string = """
<h1>LeakSight Test Report</h1>
<p>Total leakage found: ₹1,50,000</p>
<table border="1">
    <tr><th>Vendor</th><th>Amount</th></tr>
    <tr><td>Test Vendor</td><td>₹1,50,000</td></tr>
</table>
"""
HTML(string=html_string).write_pdf("test_report.pdf")
print("PDF generated successfully!")
```

### openpyxl + pandas (Excel/CSV Processing)

**What it does**: Reads Excel and CSV files (invoices, contracts, POs) and writes Excel export reports.

**How to verify:**
```python
import pandas as pd

# Read an Excel file
df = pd.read_excel("sample_invoice.xlsx")
print(df.head())
print(f"Rows: {len(df)}, Columns: {list(df.columns)}")
```

### python-docx (Word Document Parser)

**What it does**: Reads Word (.docx) contracts and extracts text and tables.

**How to verify:**
```python
from docx import Document

doc = Document("sample_contract.docx")
for para in doc.paragraphs[:5]:
    print(para.text)
for table in doc.tables:
    for row in table.rows:
        print([cell.text for cell in row.cells])
```

### Alembic (Database Migrations)

**What it does**: Manages database schema changes. When adding or modifying tables, Alembic generates migration scripts that can be applied and rolled back.

**How to verify:**
```bash
alembic current    # Shows current migration version
alembic history    # Shows all migrations
alembic upgrade head  # Applies all pending migrations
```

### Nginx (Reverse Proxy — Production Only)

**What it does**: Sits in front of FastAPI in production. Handles HTTPS, file upload size limits, static file serving.

**Not needed during development** — FastAPI's built-in server is sufficient for local testing.

***

## Part 4: Development-to-Production Transition

### When to Buy the Server

Do NOT buy a server until:
1. The full V1 pipeline works end-to-end locally
2. The Pilot Readiness Checklist passes (all 54 items)
3. A client has agreed to a paid pilot (or you need to demo remotely)

### Transition Steps

1. **Build everything locally** (Phases 0–10 of the Build Order)
2. **Pass the Pilot Readiness Checklist** on your local machine
3. **Client commits** → Buy Hetzner CX41 (~₹1,600/month)[^2]
4. **Buy domain** → ~₹500–950/year[^7][^19]
5. **Point DNS through Cloudflare** (free)[^11]
6. **Deploy using the Infra Setup Guide** (Docker Compose on server)
7. **Get Let's Encrypt SSL** (free)[^9]
8. **Set up Brevo SMTP** for notifications (free, 300 emails/day)[^13]

### What Changes Between Local and Production

| Aspect | Local Dev | Production |
|--------|-----------|------------|
| PostgreSQL | Docker on laptop, port 5432 | Docker on server, internal network only |
| Redis | Docker on laptop, port 6379 | Docker on server, internal network only |
| FastAPI | `uvicorn --reload` | `uvicorn --workers 2` behind Nginx |
| Celery | Single worker, local | Worker container, no outbound internet |
| Frontend | `npm.cmd run dev` (Vite on Windows) | Built static files served by Nginx |
| HTTPS | Not needed | Let's Encrypt via Nginx |
| Domain | localhost | yourdomain.com |
| Storage | Local folder | Encrypted Hetzner volume |
| Backups | Not needed | Daily automated pg_dump |

The application code is **identical**. Only the deployment configuration changes.

***

## Part 5: Month-by-Month Cost Timeline

| Month | Activity | Cost |
|-------|----------|------|
| Month 1–3 | Building MVP locally | **₹0** |
| Month 4 | Testing & pilot readiness | **₹0** |
| Pre-pilot | Buy domain | **₹500–950** (one-time) |
| Pilot month | Hetzner CX41 + volume | **~₹2,000** |
| Post-pilot | Ongoing if client pays | **~₹2,000/month** |

If the pilot does not convert to a paid engagement, shut down the Hetzner server (billed hourly — stop it and the cost stops). Total risk exposure for the entire experiment is roughly **₹3,000–5,000** — less than a dinner out.

---

## References

1. [Hetzner CX Series: CX11, CX21, CX31, CX41, CX51 Comparison](https://www.ekasunucu.com/en/info/hetzner-cx-series-cx11-cx21-cx31-cx41-cx51-comparison) - We compare Hetzner CX11, CX21, CX31, CX41, and CX51 servers. Find the best Hetzner CX series server ...

2. [Hetzner pricing 2026 | OMR Reviews](https://omr.com/en/reviews/product/hetzner/pricing) - CX51. €35.58/ Month. 8 vCPU Intel. 32 GB RAM. 240 GB NVMe SSD. 20 TB Traffic. 2 ... CX41. €18.92/ Mo...

3. [Quick Start - PaddleOCR Documentation](https://paddlepaddle.github.io/PaddleOCR/main/en/quick_start.html) - Awesome multilingual OCR toolkits based on PaddlePaddle (practical ultra lightweight OCR system, sup...

4. [How can I install PDFPlumber on my system?](https://www.pdfplumber.com/how-can-i-install-pdfplumber-on-my-system/) - Pip is Python's official package installer and is essential for installing PDFPlumber and its depend...

5. [Installation — Camelot 1.0.9 documentation - Read the Docs](https://camelot-py.readthedocs.io/en/master/user/install.html) - This part of the documentation covers the steps to install Camelot. Note as of v1.0.0 ghostscript is...

6. [Install WeasyPrint in Python: Easy Guide - PyTutorial](https://pytutorial.com/install-weasyprint-in-python-easy-guide/) - WeasyPrint is a powerful Python library. It converts HTML documents to PDF. This guide will help you...

7. [Domain Registration India @ Rs.499 Only - HostingRaja](https://www.hostingraja.in/domains/) - Get your domain now at unbeatable prices from HostingRaja

8. [SeekaHost India](https://www.seekahost.com/best-indian-domain-registration-sites/) - Launching a new website? Here are the top 7 best cheap Indian domain registration sites to go for an...

9. [Let's Encrypt](https://letsencrypt.org) - Let's Encrypt is a free, automated, and open Certificate Authority brought to you by the nonprofit I...

10. [SSL Certificate 2025: Free Vs Paid. The Truth About The ...](https://blog.webhostmost.com/ssl-certificate-is-scam/) - SSL certificate industry scam exposed. Learn why $200 paid SSL isn't better than free Let's Encrypt....

11. [Cloudflare pricing and plan guide (UK) - Wise](https://wise.com/gb/blog/cloudflare-pricing) - Learn how to choose the best Cloudflare plan for your business needs and how to save on costs in the...

12. [Cloudflare reinforces Free Tier commitment with 15 new features ...](https://ppc.land/cloudflare-reinforces-free-tier-commitment-with-15-new-features-announcement/) - Cloudflare reaffirms its dedication to free services on its 14th anniversary, unveiling 15 new featu...

13. [Free SMTP Server | Deliver to the Inbox Every Time - Brevo](https://www.brevo.com/free-smtp-server/) - Brevo's free SMTP server lets you send 300 free emails a day. Benefit from top-class deliverability ...

14. [10 Best Free SMTP Servers with Free Sending Tiers (2026)](https://www.sender.net/blog/free-smtp-servers/) - Finding an SMTP service that allows reliable sending without upfront costs is a common requirement f...

15. [Installing — WeasyPrint 52.5 documentation](https://doc.courtbouillon.org/weasyprint/v52.5/install.html)

16. [Quick Start - PaddleOCR Documentation](http://www.paddleocr.ai/main/en/quick_start.html) - Awesome multilingual OCR toolkits based on PaddlePaddle (practical ultra lightweight OCR system, sup...

17. [Best Python Libraries to Extract Tables From PDF in 2026 - Unstract](https://unstract.com/blog/extract-tables-from-pdf-python/) - Installation Steps. To install Pdfplumber, you can use pip, Python's package installer. Run the foll...

18. [weasyprint: Complete Python Package Guide & Tutorial [2025]](https://generalistprogrammer.com/tutorials/weasyprint-python-package-guide) - weasyprint v66.0 - The Awesome Document Factory

19. [Cheap Domain Name Registration | Buy & Save Today - GoDaddy IN](https://www.godaddy.com/en-in/domains/cheap-domain-names) - Pay less and get cheap domain names from GoDaddy. Cheap domain registration can save you money.

