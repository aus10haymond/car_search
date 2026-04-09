# Carvana SUV Tracker — Architecture & Development Plan

> **Document purpose:** This file is the authoritative specification for building the Carvana SUV Tracker.
> It is intended to direct Claude Code through all phases of development.
> Follow each phase in order. Do not skip ahead. Ask for clarification before deviating from any spec.

---

## 1. Project Overview

A scheduled Python application that:

1. Searches Carvana for a predefined list of used SUV models
2. Filters, analyzes, and scores each listing
3. Runs AI-powered analysis using a **local Ollama LLM by default**, with automatic **fallback to the Anthropic Claude API** if Ollama is unavailable
4. Saves structured results to timestamped CSV files and maintains a running history database
5. Optionally sends an email summary with price alerts
6. Logs which AI backend handled each run for transparency

### Target vehicles

| Make    | Model     | Year range |
|---------|-----------|------------|
| Honda   | CR-V      | 2021–2025  |
| Toyota  | RAV4      | 2021–2025  |
| Subaru  | Forester  | 2021–2025  |
| Kia     | Sportage  | 2021–2025  |

Hybrid trims are included in all searches and flagged in output.

---

## 2. Repository Structure

Build the following directory layout from the project root:

```
carvana-tracker/
├── main.py                  # Entry point — CLI, scheduling, orchestration
├── config.py                # All user-configurable settings (single source of truth)
├── scraper/
│   ├── __init__.py
│   ├── browser.py           # Playwright browser management and session handling
│   ├── extractor.py         # Page data extraction strategies (Next.js, Apollo, DOM)
│   └── urls.py              # Carvana URL builder (base64-encoded filter params)
├── analysis/
│   ├── __init__.py
│   ├── rules.py             # Rule-based filtering and scoring (Option 1)
│   ├── llm.py               # LLM analysis orchestrator — Ollama + API fallback (Options 2/3)
│   ├── ollama_client.py     # Ollama local LLM client
│   └── anthropic_client.py  # Anthropic API client (fallback)
├── storage/
│   ├── __init__.py
│   ├── csv_writer.py        # CSV output — timestamped + latest symlink
│   └── history_db.py        # SQLite history database for trend detection
├── notifications/
│   ├── __init__.py
│   └── email_alert.py       # Gmail SMTP email summaries and price alerts
├── utils/
│   ├── __init__.py
│   ├── logging_config.py    # Structured logging setup
│   └── payment_calc.py      # Monthly payment and cost calculations
├── tests/
│   ├── test_urls.py
│   ├── test_rules.py
│   ├── test_payment_calc.py
│   └── test_llm_fallback.py
├── requirements.txt
├── .env.example             # Template for environment variables
├── .env                     # Actual secrets — never commit this
└── README.md
```

---

## 3. Configuration (`config.py`)

All user-facing settings live here. **Never hardcode values elsewhere** — always import from config.

```python
# config.py — all values shown are defaults; user edits this file before first run

import os
from dotenv import load_dotenv
load_dotenv()

# ── Vehicles ──────────────────────────────────────────────────────────────────
VEHICLES = [
    # (make, model, min_year, max_year)
    ("Honda",  "CR-V",     2021, 2025),
    ("Toyota", "RAV4",     2021, 2025),
    ("Subaru", "Forester", 2021, 2025),
    ("Kia",    "Sportage", 2021, 2025),
]

# ── Filters ───────────────────────────────────────────────────────────────────
MAX_PRICE    = 45000
MAX_MILEAGE  = 80000
MIN_YEAR     = 2021
MAX_YEAR     = 2025

# ── Location ──────────────────────────────────────────────────────────────────
ZIP_CODE = "85001"   # Phoenix, AZ — used by Carvana for shipping estimates

# ── Payment calculator ────────────────────────────────────────────────────────
DOWN_PAYMENT     = 3000    # dollars
INTEREST_RATE    = 7.5     # APR percent
LOAN_TERM_MONTHS = 60

# ── Scheduling ────────────────────────────────────────────────────────────────
CHECK_INTERVAL_HOURS = 6

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR     = "./carvana_results"
DB_PATH        = "./carvana_results/history.db"
LOG_FILE       = "./carvana_results/tracker.log"

# ── AI analysis ───────────────────────────────────────────────────────────────
# Primary: local Ollama
OLLAMA_ENABLED  = True
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "llama3.1:8b"     # Change to llama3.1:70b for better quality (needs ~40GB RAM)
OLLAMA_TIMEOUT  = 120               # seconds — first model load can be slow

# Fallback: Anthropic API
ANTHROPIC_ENABLED   = True
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL     = "claude-haiku-4-5-20251001"  # Cheapest model; sufficient for this task
ANTHROPIC_MAX_TOKENS = 1500

# ── Alerts ────────────────────────────────────────────────────────────────────
ALERT_PRICE_THRESHOLD = 32000   # Email alert if any listing falls below this price
ALERT_HYBRID_ONLY     = False   # If True, only alert on hybrid listings

# ── Email (optional) ──────────────────────────────────────────────────────────
SEND_EMAIL     = False
EMAIL_FROM     = os.getenv("EMAIL_FROM", "")
EMAIL_TO       = os.getenv("EMAIL_TO", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # Gmail App Password

# ── Scraping behaviour ────────────────────────────────────────────────────────
HEADLESS                 = True
REQUEST_DELAY_SECONDS    = 4
PAGE_TIMEOUT_SECONDS     = 30
MAX_PAGES_PER_SEARCH     = 5    # Carvana paginates; cap to avoid long runs
```

### Environment variables (`.env`)

Secrets are never in `config.py`. They load from `.env` via `python-dotenv`:

```
ANTHROPIC_API_KEY=sk-ant-...
EMAIL_FROM=you@gmail.com
EMAIL_TO=you@gmail.com
EMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

Provide a `.env.example` with all keys present but values blank. Add `.env` to `.gitignore`.

---

## 4. Module Specifications

### 4.1 `scraper/urls.py`

Builds Carvana search URLs. Carvana encodes filters as JSON → base64 in the `cvnaid` query parameter.

**Function to implement:**

```python
def build_search_url(make: str, model: str, min_year: int, max_year: int, page: int = 1) -> str:
    """
    Returns a Carvana search URL with base64-encoded filter params.
    Example output:
      https://www.carvana.com/cars/filters?cvnaid=<base64>&page=2
    
    Filter JSON shape:
    {
      "filters": {
        "makes": [{"name": "Toyota", "models": [{"name": "RAV4"}]}],
        "year": {"min": 2021, "max": 2025}
      }
    }
    """
```

Write a unit test in `tests/test_urls.py` that:
- Verifies the URL contains the `cvnaid` param
- Decodes the base64 and confirms the JSON contains the correct make/model/year
- Verifies the page param is appended when > 1

---

### 4.2 `scraper/browser.py`

Manages Playwright browser lifecycle. Uses headless Chromium with a realistic user agent to reduce bot detection.

**Key requirements:**

- Single browser instance per scraper run (not per search) — reuse context across all vehicle searches
- Set a realistic user agent string (current Chrome on Windows)
- Set viewport to 1280×800
- Implement a `get_page_content(url: str) -> str` function that returns raw HTML after waiting for `networkidle`
- Add a configurable delay after each page load (`REQUEST_DELAY_SECONDS` from config)
- Handle `TimeoutError` gracefully — log a warning and return empty string, do not raise
- Close the browser in a `finally` block to prevent zombie processes
- Do not use proxy by default; add a `PROXY_URL` config option stubbed as empty string for future use

---

### 4.3 `scraper/extractor.py`

Extracts structured vehicle data from a loaded Carvana page. Implements three strategies in priority order:

**Strategy 1 — `__NEXT_DATA__` JSON (highest priority)**

Carvana is a Next.js app. The server-side rendered JSON is embedded in a `<script id="__NEXT_DATA__">` tag. Parse this first as it is the most complete and stable source.

```python
def extract_from_next_data(html: str) -> list[dict]:
    """
    Parse the __NEXT_DATA__ JSON blob from the page HTML.
    Navigate: props -> pageProps -> (vehicles | inventory.vehicles | initialData.vehicles)
    Return a list of raw vehicle dicts. Return [] if not found.
    """
```

**Strategy 2 — Apollo/GraphQL cache**

Carvana uses Apollo Client which embeds a cache object in the page as a JavaScript variable. Use regex to extract the JSON blob if Strategy 1 returns no results.

```python
def extract_from_apollo_cache(html: str) -> list[dict]:
    """
    Use regex to find __APOLLO_STATE__ or similar window variable.
    Filter keys where __typename is Vehicle, Car, or InventoryItem.
    Return [] if not found.
    """
```

**Strategy 3 — DOM scraping (last resort)**

Falls back to parsing HTML listing cards directly using BeautifulSoup. This is the most fragile approach and most likely to break on Carvana UI changes.

```python
def extract_from_dom(html: str) -> list[dict]:
    """
    Parse listing cards using BeautifulSoup.
    Target selectors (in priority order, use first that matches):
      - [data-qa="vehicle-card"]
      - .vehicle-card
      - [class*="VehicleCard"]
    Extract: title, price, mileage, monthly payment, listing URL.
    Return [] if no cards found.
    """
```

**Normalizer:**

All three strategies feed into a shared normalizer:

```python
def normalize_vehicle(raw: dict, make: str, model: str, strategy: str) -> dict | None:
    """
    Converts a raw vehicle dict (from any strategy) into the standard schema below.
    Returns None if the listing is missing price or cannot be parsed.
    Log a debug message identifying which strategy produced this record.

    Standard schema:
    {
        "vin":              str,
        "year":             int | None,
        "make":             str,
        "model":            str,
        "trim":             str,
        "price":            float | None,
        "mileage":          int | None,
        "monthly_carvana":  float | None,   # Carvana's quoted monthly payment
        "shipping":         float | None,   # Carvana's shipping/delivery fee
        "color_exterior":   str,
        "color_interior":   str,
        "url":              str,
        "extraction_strategy": str,         # "next_data" | "apollo" | "dom"
        "scraped_at":       str,            # ISO 8601 timestamp
    }
    """
```

---

### 4.4 `utils/payment_calc.py`

Pure functions with no side effects. Write unit tests for all of these.

```python
def estimate_monthly_payment(price: float, down: float, apr_pct: float, months: int) -> float:
    """Standard amortizing loan formula. Returns 0.0 if principal <= 0."""

def total_cost_of_ownership(price: float, shipping: float | None) -> float:
    """Price + shipping. Treats None shipping as 0."""

def price_per_mile(price: float, mileage: int | None) -> float | None:
    """Returns None if mileage is None or 0."""

def depreciation_estimate(price: float, year: int, current_year: int = 2025) -> float:
    """
    Rough estimate of remaining value after 5 years.
    Uses a simple declining-balance model at 15% per year.
    Not financial advice — clearly label this as an estimate in all output.
    """
```

---

### 4.5 `analysis/rules.py`

Rule-based filtering and scoring. This runs on every listing before any LLM is called. It is fast, free, and deterministic.

**Filter function:**

```python
def apply_filters(listings: list[dict]) -> list[dict]:
    """
    Remove listings that exceed MAX_PRICE, MAX_MILEAGE,
    are outside MIN_YEAR/MAX_YEAR range, or have no price.
    Log how many listings were removed and why.
    """
```

**Enrichment function:**

```python
def enrich_listing(listing: dict) -> dict:
    """
    Add computed fields to a listing dict:
    - monthly_estimated: float         (from payment_calc)
    - total_with_shipping: float       (from payment_calc)
    - price_per_mile: float | None     (from payment_calc)
    - is_hybrid: bool                  (True if "hybrid", "hev", "phev", "prime" in trim.lower())
    - age_years: int                   (current_year - listing year)
    - value_score: float               (see scoring below)
    """
```

**Value score algorithm:**

Produce a `value_score` from 0–100 for each listing. Higher is better. This score is used to sort output and is passed to the LLM as context.

Scoring components (weights must sum to 100):

| Component | Weight | Logic |
|---|---|---|
| Price vs. group average | 35 | Percentage below average price for same make/model/year group. Capped at ±30% |
| Mileage | 25 | Inverse linear scale. 0 miles = 25pts, 80,000 miles = 0pts |
| Age | 20 | Newer = better. 2025 = 20pts, 2021 = 0pts |
| Hybrid bonus | 10 | +10 if `is_hybrid` is True, else 0 |
| Shipping penalty | 10 | 10pts if shipping = 0 or None, scales down linearly to 0pts at $1,500 shipping |

Note: The price component requires computing the group average across all listings of the same make/model/year before scoring individual listings. Compute averages first, then score.

Write tests in `tests/test_rules.py` covering: filter removal, hybrid detection, score boundary conditions.

---

### 4.6 `analysis/ollama_client.py`

Handles all communication with a locally running Ollama instance.

```python
class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int): ...

    def is_available(self) -> bool:
        """
        GET {base_url}/api/tags — returns True if Ollama is running and
        the configured model is in the response. Returns False on any exception.
        Do not raise. Logs result at DEBUG level.
        """

    def analyze(self, prompt: str) -> str:
        """
        POST to {base_url}/api/generate with stream=False.
        Returns the response text.
        Raises OllamaUnavailableError on connection failure or timeout.
        Raises OllamaModelError if model not found (HTTP 404).
        """
```

Define custom exceptions `OllamaUnavailableError` and `OllamaModelError` in this module.

---

### 4.7 `analysis/anthropic_client.py`

Wraps the Anthropic Python SDK for the fallback path.

```python
class AnthropicClient:
    def __init__(self, api_key: str, model: str, max_tokens: int): ...

    def is_configured(self) -> bool:
        """Returns True if api_key is non-empty."""

    def analyze(self, prompt: str) -> str:
        """
        Calls anthropic.messages.create() with the user prompt.
        Returns the text content of the first message block.
        Raises AnthropicUnavailableError on API errors.
        Logs token usage at DEBUG level after each call.
        """
```

Define `AnthropicUnavailableError` in this module.

---

### 4.8 `analysis/llm.py` — The Fallback Orchestrator

This is the central logic for AI backend selection. It is the only module that imports both clients.

```python
class LLMAnalyzer:
    def __init__(self):
        self.ollama = OllamaClient(...)    # from config
        self.anthropic = AnthropicClient(...)  # from config
        self.backend_used: str | None = None   # set after each analyze() call

    def analyze(self, listings: list[dict]) -> LLMResult:
        """
        1. If OLLAMA_ENABLED and ollama.is_available():
             → try ollama.analyze(prompt)
             → on success: set backend_used = "ollama", return result
             → on OllamaUnavailableError or OllamaModelError:
                 log WARNING with reason, fall through to step 2
        
        2. If ANTHROPIC_ENABLED and anthropic.is_configured():
             → try anthropic.analyze(prompt)
             → on success: set backend_used = "anthropic_api", return result
             → on AnthropicUnavailableError:
                 log ERROR with reason, fall through to step 3
        
        3. Neither backend available:
             → set backend_used = "none"
             → return LLMResult with analysis = None and a clear warning message
        
        Never raise from this method. Always return an LLMResult.
        """

    def build_prompt(self, listings: list[dict]) -> str:
        """
        Builds the analysis prompt. See Section 5 for full prompt spec.
        """
```

```python
@dataclass
class LLMResult:
    analysis:     str | None    # The LLM's text output, or None if unavailable
    backend_used: str           # "ollama" | "anthropic_api" | "none"
    model_used:   str           # Specific model string, e.g. "llama3.1:8b"
    tokens_used:  int | None    # None for Ollama (not always available)
    latency_ms:   int           # Wall-clock time for the LLM call
    error:        str | None    # Error message if backend failed, else None
```

---

## 5. LLM Prompt Specification

The prompt passed to both Ollama and the Anthropic API must be identical. Build it in `llm.py:build_prompt()`.

### Structure

```
[SYSTEM CONTEXT]
You are an automotive analyst helping a buyer find the best used SUV deal on Carvana.
The buyer is located in Phoenix, AZ. Their budget is ${MAX_PRICE:,}.
They are interested in hybrid trims. They plan to finance with ${DOWN_PAYMENT:,} down,
at {INTEREST_RATE}% APR over {LOAN_TERM_MONTHS} months.
Analyze the listings below and provide a clear, practical recommendation.
Do not speculate beyond the data provided. Flag any data that looks unusual.

[LISTINGS DATA]
Provide a markdown table with columns:
  Year | Make | Model | Trim | Price | Mileage | Est. Payment | Shipping | Value Score | Hybrid

Then provide the top 5 listings formatted as:
  Rank | Vehicle | Why it stands out

[ANALYSIS REQUEST]
1. Identify the top 3 overall best deals, explaining your reasoning for each.
2. Identify the top hybrid deal specifically.
3. Flag any listings that appear to be unusual (suspiciously low price, very high mileage for year, etc.)
4. Note any patterns across the full dataset (e.g., "RAV4 Hybrids are commanding a $3,000 premium over gas models in this dataset").
5. Give one clear final recommendation with a brief rationale.

Keep the response under 600 words. Use plain language. Avoid filler phrases.
```

### Data formatting rules for the prompt

- Round all prices to nearest dollar, no cents
- Round mileage to nearest hundred
- Format monthly payments as `$XXX/mo`
- Include `value_score` as an integer 0–100
- Mark hybrid listings clearly with `[HYBRID]` in the trim column
- Cap the listings table at 30 rows to stay within context limits — use the top 30 by `value_score`
- Include a header line with run timestamp, total listings found before filtering, and listings shown

---

## 6. Storage

### 6.1 CSV output (`storage/csv_writer.py`)

Write two files on each run:

1. **Timestamped file:** `{OUTPUT_DIR}/carvana_YYYYMMDD_HHMMSS.csv`
2. **Latest file:** `{OUTPUT_DIR}/carvana_latest.csv` — always overwritten

CSV columns (in this order):

```
run_id, scraped_at, year, make, model, trim, price, mileage,
monthly_carvana, monthly_estimated, shipping, total_with_shipping,
price_per_mile, value_score, is_hybrid, vin, url,
llm_backend_used, extraction_strategy, color_exterior, color_interior
```

`run_id` is a UUID4 generated once per run and shared across all rows from that run.

### 6.2 SQLite history database (`storage/history_db.py`)

Maintain a persistent SQLite database at `DB_PATH` to enable trend detection across runs.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    run_at          TEXT NOT NULL,   -- ISO 8601
    listings_found  INTEGER,
    listings_saved  INTEGER,
    llm_backend     TEXT,
    llm_model       TEXT,
    duration_seconds REAL
);

CREATE TABLE IF NOT EXISTS listings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL REFERENCES runs(run_id),
    vin                 TEXT,
    scraped_at          TEXT,
    year                INTEGER,
    make                TEXT,
    model               TEXT,
    trim                TEXT,
    price               REAL,
    mileage             INTEGER,
    monthly_estimated   REAL,
    shipping            REAL,
    value_score         REAL,
    is_hybrid           INTEGER,  -- 0 or 1
    url                 TEXT,
    UNIQUE(run_id, vin)           -- prevent duplicate VINs per run
);

CREATE TABLE IF NOT EXISTS price_history (
    vin         TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    run_at      TEXT NOT NULL,
    price       REAL NOT NULL,
    PRIMARY KEY (vin, run_id)
);
```

**Functions to implement:**

```python
def save_run(run: RunRecord) -> None: ...
def save_listings(listings: list[dict], run_id: str) -> None: ...
def get_price_history(vin: str) -> list[dict]: ...

def get_new_listings(current_vins: set[str]) -> set[str]:
    """Return VINs in current_vins that have never appeared in the DB before."""

def get_price_drops(listings: list[dict], threshold_pct: float = 5.0) -> list[dict]:
    """
    For each listing with a previous price in the DB,
    return listings where price dropped by >= threshold_pct since last seen.
    """
```

---

## 7. Notifications (`notifications/email_alert.py`)

Uses Gmail SMTP over SSL (port 465). Only sends if `SEND_EMAIL = True` in config.

**Trigger conditions (send if any are true):**

- Any listing is below `ALERT_PRICE_THRESHOLD`
- Any listing in `get_new_listings()` that scores above 70
- Any listing in `get_price_drops()` that dropped 5%+

**Email content:**

- Subject: `Carvana Tracker — {N} listings | {M} alerts` (M = 0 if no alert conditions)
- Body: HTML email with:
  - Summary header: run time, total found, total matching filters
  - Alert section (if any): bold listings triggering alerts with direct Carvana links
  - Full results table (top 20 by value score)
  - LLM analysis section (if available) — clearly labelled with which backend produced it
  - Footer: which AI backend was used, script version

---

## 8. Entry Point (`main.py`)

### CLI interface

```
python main.py                   # Run once immediately
python main.py --schedule        # Run now, then repeat every CHECK_INTERVAL_HOURS
python main.py --once            # Explicit single run (same as no args)
python main.py --dry-run         # Run scraper and analysis but do not save or email
python main.py --no-llm          # Skip LLM analysis entirely (rules only)
python main.py --backend ollama  # Force Ollama, no fallback
python main.py --backend api     # Force Anthropic API, no Ollama
python main.py --email           # Force email send this run regardless of config
python main.py --history         # Print price history summary from DB and exit
python main.py --check-setup     # Validate config, test Ollama, test API key, exit
```

### Run lifecycle (one full cycle)

```
1. Parse CLI args
2. Load config, validate required fields
3. Initialize logging (file + console)
4. Generate run_id (UUID4)
5. For each vehicle in VEHICLES:
   a. Build Carvana search URL
   b. Load page(s) via browser.py (up to MAX_PAGES_PER_SEARCH)
   c. Extract listings via extractor.py (try strategies 1→2→3)
   d. Normalize all raw records
6. Merge all listings into one list, deduplicate by VIN
7. Apply rule-based filters (rules.py)
8. Enrich listings with computed fields and value scores
9. Unless --no-llm: run LLM analysis (llm.py — Ollama → API fallback)
10. Save to CSV (csv_writer.py)
11. Save to SQLite DB (history_db.py)
12. Detect new listings and price drops (history_db.py)
13. Print formatted summary table to stdout (tabulate)
14. If SEND_EMAIL or --email: send email (email_alert.py)
15. Log run completion with duration, backend used, listing count
```

### Scheduling

When `--schedule` is passed:
- Run the full lifecycle immediately on start
- Use the `schedule` library to repeat every `CHECK_INTERVAL_HOURS`
- Log a heartbeat message every 30 minutes while idle so the user can confirm the process is alive
- Handle `KeyboardInterrupt` (Ctrl+C) cleanly — log "Shutting down" and exit 0

---

## 9. Logging

Configure in `utils/logging_config.py`. Apply at startup in `main.py`.

- **Console:** INFO level, human-readable format with timestamps
- **File:** DEBUG level, written to `LOG_FILE`, rotated at 5MB, keep 3 backups
- **Always log:**
  - Which extraction strategy succeeded for each vehicle search
  - How many listings were removed by each filter rule and why
  - Which LLM backend was attempted, which succeeded, which failed and why
  - Token usage and latency for each LLM call
  - Total run duration

---

## 10. Dependencies (`requirements.txt`)

```
playwright>=1.40.0
beautifulsoup4>=4.12.0
requests>=2.31.0
anthropic>=0.25.0
schedule>=1.2.0
pandas>=2.0.0
tabulate>=0.9.0
python-dotenv>=1.0.0
```

After installing, run:
```bash
playwright install chromium
```

---

## 11. Development Phases

Implement in this order. Each phase should be independently runnable and testable before moving to the next.

### Phase 1 — Foundation
- [ ] Create full directory structure with `__init__.py` files
- [ ] Implement `config.py` with all settings and `.env` loading
- [ ] Implement `utils/logging_config.py`
- [ ] Implement `utils/payment_calc.py` with unit tests
- [ ] Implement `scraper/urls.py` with unit tests
- [ ] Verify: `python -c "from scraper.urls import build_search_url; print(build_search_url('Toyota', 'RAV4', 2021, 2025))"`

### Phase 2 — Scraper
- [ ] Implement `scraper/browser.py`
- [ ] Implement `scraper/extractor.py` (all three strategies + normalizer)
- [ ] Implement a standalone `scrape_one.py` debug script that scrapes one vehicle, prints raw results to stdout, and exits — useful for testing without running the full pipeline
- [ ] Verify extraction works for at least one vehicle before proceeding

### Phase 3 — Rules & Storage
- [ ] Implement `analysis/rules.py` with unit tests (especially value score)
- [ ] Implement `storage/csv_writer.py`
- [ ] Implement `storage/history_db.py`
- [ ] Wire Phase 2 + 3 together in a minimal `main.py` that scrapes, filters, enriches, and saves to CSV + DB

### Phase 4 — LLM Analysis
- [ ] Implement `analysis/ollama_client.py` with `is_available()` and `analyze()`
- [ ] Implement `analysis/anthropic_client.py`
- [ ] Implement `analysis/llm.py` orchestrator with fallback logic
- [ ] Implement `tests/test_llm_fallback.py` — mock both clients, verify fallback triggers correctly
- [ ] Add `--check-setup` command to test both backends and report status

### Phase 5 — Notifications & CLI
- [ ] Implement `notifications/email_alert.py`
- [ ] Complete `main.py` with full CLI argument handling and scheduling
- [ ] End-to-end test: run `python main.py --dry-run` and verify all output without saving

### Phase 6 — Polish
- [ ] Add `--history` command
- [ ] Add price drop detection and new listing detection using history DB
- [ ] Write `README.md` with setup instructions, config reference, and example output
- [ ] Add `scrape_one.py` debug helper to `.gitignore` if it contains any credentials

---

## 12. Testing

Run the test suite with:
```bash
python -m pytest tests/ -v
```

### Required test coverage

| Test file | What to cover |
|---|---|
| `test_urls.py` | URL structure, base64 decode, page param |
| `test_payment_calc.py` | All four functions, edge cases (zero price, zero mileage, zero APR) |
| `test_rules.py` | Filter removal, hybrid detection, value score boundaries, group average calculation |
| `test_llm_fallback.py` | Ollama available → uses Ollama; Ollama fails → uses API; both fail → returns `LLMResult` with `backend_used="none"` |

Use `unittest.mock` to mock HTTP calls in all LLM tests. Do not make real network calls in tests.

---

## 13. Known Limitations & Constraints

Document these clearly in `README.md` so the user understands system boundaries:

1. **Bot detection:** Carvana uses PerimeterX. Headless Chromium passes most of the time but is not guaranteed. If scraping consistently fails, the next step is residential proxies (not in scope for this build).

2. **Shipping costs:** Carvana does not always expose shipping costs in search results — they may only appear on individual listing pages. The scraper captures shipping when available but it will often be `None`. Do not treat `None` as $0 in calculations — label it "unavailable" in output.

3. **LLM analysis quality:** The local Ollama model (e.g., Llama 3.1 8B) will produce lower-quality analysis than the Anthropic API. The `LLMResult.backend_used` field must be prominently displayed in all output so the user always knows which backend produced the analysis.

4. **Price data accuracy:** Carvana prices change frequently. Each CSV row is a snapshot at `scraped_at` time. Do not treat historical CSVs as current pricing.

5. **No official API:** Carvana does not provide a public API. All data extraction depends on scraping, which can break if Carvana changes their frontend. The three-strategy extractor is designed to be resilient, but maintenance may be required over time.

6. **Scheduler requires machine to be on:** The `--schedule` mode requires the process to stay running. It does not compensate for missed runs if the machine sleeps. For always-on scheduling, deploy to a cloud VM or use the OS task scheduler (`cron` / Task Scheduler) to invoke `python main.py --once` on a timer instead.

---

## 14. Out of Scope

The following are explicitly not part of this build:

- Web UI or dashboard
- Proxy management or residential proxy integration
- Scraping individual listing detail pages (only search results pages)
- Price negotiation automation or any interaction with Carvana's checkout flow
- Support for vehicles other than the four listed in Section 1
- Mobile app or notifications via SMS/push
- Deployment configuration (Docker, systemd, etc.)

These can be addressed in future iterations.
