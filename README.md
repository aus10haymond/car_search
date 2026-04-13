# Carvana SUV Tracker

Scheduled Python tool that scrapes Carvana for used SUVs, scores and filters listings, runs AI analysis via the Anthropic API (with local Ollama fallback), and sends an HTML email summary with price trend charts.

---

## What it does

Each run:

1. Loads one or more **search profiles** from `profiles.yaml` (vehicles, filters, recipients)
2. Scrapes Carvana using headless Chromium, across configured fuel types (hybrid, gas, or all)
3. Deduplicates by VIN and applies per-profile filters (price, mileage, year, trim keywords)
4. Scores each listing 0–100 based on price vs. group average, mileage, age, hybrid status, shipping, and model preference
5. Runs AI analysis on the top listings using the Anthropic API (or local Ollama as fallback)
6. Saves results to a timestamped CSV and a SQLite history database
7. Detects new listings and price drops since the last run
8. Sends an HTML email with alerts, a top-20 table, price trend charts, and AI analysis

---

## Project structure

```
car_search/
├── main.py                   # Entry point — CLI, scheduling, run orchestration
├── config.py                 # Global settings (LLM, email, scraping, paths)
├── profiles.py               # SearchProfile dataclass + profiles.yaml loader
├── profiles.yaml             # Your search profiles (vehicles, filters, recipients)
├── setup_gmail_oauth.py      # One-time Gmail OAuth2 setup script
├── scraper/
│   ├── urls.py               # Carvana URL builder (base64-encoded filter params)
│   ├── browser.py            # Playwright browser management
│   └── extractor.py          # Data extraction (Next.js, Apollo, DOM fallback)
├── analysis/
│   ├── rules.py              # Rule-based filtering, enrichment, and value scoring
│   ├── llm.py                # LLM orchestrator — Anthropic API → Ollama fallback
│   ├── anthropic_client.py   # Anthropic API client (primary)
│   └── ollama_client.py      # Local Ollama client (fallback)
├── storage/
│   ├── csv_writer.py         # Timestamped CSV output
│   ├── history_db.py         # SQLite run history and price trend tracking
│   └── trends.py             # Price trend chart generation (HTML)
├── notifications/
│   └── email_alert.py        # Gmail API email summary and price alerts
├── utils/
│   ├── payment_calc.py       # Monthly payment, TCO, price-per-mile calculations
│   └── logging_config.py     # Structured logging (console + file)
├── tests/
│   ├── test_urls.py
│   ├── test_payment_calc.py
│   ├── test_rules.py
│   └── test_llm_fallback.py
├── carvana_tracker.py        # Legacy single-file prototype (not used by main.py)
├── requirements.txt
├── .env.example
└── .env                      # Secrets — never commit
```

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure profiles

Edit `profiles.yaml` to define your search criteria. The file is self-documented with inline comments. Each profile specifies its own vehicles, filters, and email recipients.

### 3. Set your secrets

Copy `.env.example` to `.env` and fill in your values:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...

# Gmail API — fill in sender and OAuth credentials (see step 4)
GMAIL_SENDER=you@gmail.com
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=   # written automatically by setup_gmail_oauth.py

EMAIL_FROM_NAME=Carvana Tracker
```

### 4. Set up Gmail OAuth (one time)

The tracker sends email through the Gmail API using OAuth2. You need a Google Cloud project with the Gmail API enabled and an OAuth client ID.

```bash
# Install the one-time auth dependency
pip install google-auth-oauthlib

# Run the interactive setup — opens a browser to authorize your Gmail account
python setup_gmail_oauth.py
```

**Steps before running:**
1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create or select a project
2. Enable the Gmail API: APIs & Services → Enable APIs → search "Gmail API" → Enable
3. Create OAuth credentials: APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app
4. Copy the Client ID and Client Secret when prompted by the script

The script writes `GMAIL_REFRESH_TOKEN` to `.env` automatically. You won't need `google-auth-oauthlib` again after this.

### 5. Verify setup

```bash
python main.py --check-setup
```

This tests Ollama connectivity, the Anthropic API key, and Gmail credentials without running a full scrape.

---

## Usage

```bash
# Run once and exit (default)
python main.py

# Explicit single run
python main.py --once

# Run on a schedule (every CHECK_INTERVAL_HOURS hours)
python main.py --schedule

# Dry run — scrape and analyze but do not save or send email
python main.py --dry-run

# Skip LLM analysis (rules-based scoring only)
python main.py --no-llm

# Force a specific LLM backend
python main.py --backend api
python main.py --backend ollama

# Force email send regardless of config
python main.py --email

# Suppress email for this run
python main.py --no-email

# Print run history, per-model pricing, and all-time stats
python main.py --history

# Validate config and test all backends
python main.py --check-setup

# Recompute price trend stats from existing DB data (utility)
python main.py --backfill-stats

# Show DEBUG-level output on the console
python main.py --debug
```

---

## profiles.yaml reference

All per-search settings live in `profiles.yaml`. Multiple profiles can run in one invocation, each with its own vehicles, filters, and recipients.

```yaml
profiles:
  - profile_id: my_search          # unique slug
    label: "My SUV Search"         # shown in email subject and body

    vehicles:                      # [make, model] pairs to search
      - [Honda, CR-V]
      - [Toyota, RAV4]

    max_price: 30000               # omit or set to null for no upper limit
    max_mileage: 80000
    min_year: 2021
    max_year: 2025

    fuel_type_filters: [Hybrid, Gas]   # Hybrid | Gas | null (all). Runs a separate
                                       # Carvana search per type. Omit for all trims.

    model_preference: [CR-V, RAV4]     # ordered best→worst; affects sort order and
                                       # value score bonus. Omit for pure score ranking.

    excluded_trim_keywords: [sport]    # case-insensitive substrings to drop from results

    reference_doc_path: ./MY_REFERENCE.md  # optional markdown context fed to the LLM

    email_to:
      - you@gmail.com
```

---

## config.py reference

Global settings not specific to any one search profile.

| Setting | Default | Description |
| --- | --- | --- |
| `ZIP_CODE` | 85286 | Used by Carvana to estimate shipping costs |
| `DOWN_PAYMENT` | 3000 | Down payment used in monthly payment estimates |
| `INTEREST_RATE` | 7.5 | APR used in monthly payment estimates |
| `LOAN_TERM_MONTHS` | 60 | Loan term in months |
| `CHECK_INTERVAL_HOURS` | 24 | How often to run in `--schedule` mode |
| `ANTHROPIC_ENABLED` | True | Enable Anthropic API (primary LLM) |
| `ANTHROPIC_MODEL` | claude-haiku-4-5-20251001 | Anthropic model to use |
| `OLLAMA_ENABLED` | True | Enable local Ollama (fallback LLM) |
| `OLLAMA_MODEL` | gemma3:4b | Ollama model to use |
| `OLLAMA_TIMEOUT` | 300 | Seconds before Ollama request times out |
| `SEND_EMAIL` | True | Send email summary after each run |
| `MAX_PAGES_PER_SEARCH` | 5 | Maximum Carvana result pages to scrape per vehicle/fuel-type combination |

---

## AI analysis

The tracker tries backends in this order:

1. **Anthropic API** — higher quality, costs fractions of a cent per run. Set `ANTHROPIC_ENABLED = True` and provide `ANTHROPIC_API_KEY` in `.env`.
2. **Ollama (local)** — free and private, runs on your machine. `gemma3:4b` is a good balance of speed and quality. The model is pre-warmed in a background thread at run start. Requires Ollama to be running (`ollama serve`).
3. **None** — if both fail, the run completes without AI analysis. Scoring and email still work.

Which backend was used is always shown in the terminal output, email footer, and CSV `llm_backend_used` column.

A `reference_doc_path` in your profile can supply the LLM with extra context (reliability notes, owner reviews, known issues, etc.) to improve analysis quality.

---

## Value score (0–100)

Each listing is scored before LLM analysis. Higher is better.

| Component | Weight | Logic |
| --- | --- | --- |
| Price vs. group average | 35 | % below average price for same make/model. Capped at ±30% |
| Mileage | 25 | Inverse linear: 0 mi = 25 pts, max\_mileage = 0 pts |
| Age | 20 | Newer = better. max\_year = 20 pts, min\_year = 0 pts |
| Hybrid bonus | 10 | +10 if `fuel_type_filters` includes Hybrid and trim matches |
| Shipping penalty | 10 | 10 pts if no shipping fee; scales to 0 at $1,500 shipping |

Model preference (from your profile) adds a tie-breaking sort on top of the raw score.

---

## Scheduling with Windows Task Scheduler

To run the tracker automatically every day:

1. Create `run_tracker.bat` in the project root:

   ```bat
   @echo off
   cd /d C:\path\to\car_search
   python main.py --once
   ```

2. Open Task Scheduler → Create Basic Task
3. Set the trigger to **Daily** at your preferred time
4. Set the action to run `run_tracker.bat`
5. In **Settings**, check "Run task as soon as possible after a scheduled start is missed"

---

## Output files

All output is written to `carvana_results/` (gitignored):

| File | Description |
| --- | --- |
| `carvana_YYYYMMDD_HHMMSS.csv` | Timestamped results for each run |
| `carvana_latest.csv` | Always overwritten with the most recent run |
| `history.db` | SQLite database tracking all runs, listings, and price history |
| `tracker.log` | Rolling log file (5 MB max, 3 backups) |
| `logs/run_*.log` | Per-run log files for debugging |

---

## Tests

```bash
python -m pytest tests/ -v
```

| Test file | Covers |
| --- | --- |
| `test_urls.py` | URL structure, base64 encoding, page param, fuel type filter |
| `test_payment_calc.py` | Monthly payment, TCO, price per mile, depreciation |
| `test_rules.py` | Filter removal, hybrid detection, value score boundaries |
| `test_llm_fallback.py` | Anthropic→Ollama fallback logic, both-fail case |

---

## Known limitations

- **Bot detection:** Carvana uses PerimeterX. Headless Chromium passes most of the time. If scraping starts failing consistently, residential proxies would be the next step (out of scope).
- **Shipping costs:** Often not available in search results. Shown as `None` in the CSV when unavailable — not treated as $0.
- **Ollama cold starts:** First run after machine restart can be slow. The pre-warmup mitigates this but requires Ollama to already be running (`ollama serve`).
- **No official API:** Carvana doesn't provide a public API. The scraper can break if Carvana changes their frontend. The three-strategy extractor (Next.js → Apollo → DOM) is designed to be resilient but may require maintenance.
- **Prices change constantly.** Each CSV row is a snapshot at scrape time.
- **Scheduler requires machine to be on.** `--schedule` mode doesn't compensate for missed runs if the machine sleeps. Use Windows Task Scheduler with `--once` for more reliable execution.
