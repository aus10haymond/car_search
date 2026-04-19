# Carvana SUV Tracker

Scheduled Python tool that scrapes Carvana for used SUVs, scores and filters listings, runs AI analysis, and sends an HTML email summary with price trend charts.

---

## What it does

Each run:

1. Loads one or more **search profiles** from `profiles.yaml` (vehicles, filters, recipients)
2. Scrapes Carvana using headless Chromium across configured fuel types (hybrid, gas, or all)
3. Deduplicates by VIN and applies per-profile filters (price, mileage, year, trim exclusions)
4. Scores each listing 0–100 based on price vs. group average, mileage, age, hybrid status, and model preference
5. Runs **per-make LLM analysis** using isolated reference docs to prevent cross-brand terminology bleed
6. Runs a **cross-model synthesis** LLM call to rank and recommend the top 3 picks across all makes
7. Validates LLM output for brand-bleed errors; auto-corrects if possible
8. Saves results to a timestamped CSV and a SQLite history database
9. Detects new listings and price drops since the last run
10. Sends an HTML email with the top listings table (LLM picks pinned to the top), price trend charts, trim key, and AI analysis

---

## Project structure

```
car_search/
├── main.py                   # Entry point — CLI, scheduling, run orchestration
├── config.py                 # Global settings (LLM, email, scraping, paths)
├── profiles.py               # SearchProfile dataclass + profiles.yaml loader
├── profiles.yaml             # Your search profiles (vehicles, filters, recipients)
├── scraper/
│   ├── urls.py               # Carvana URL builder (base64-encoded filter params)
│   ├── browser.py            # Playwright browser management
│   └── extractor.py          # Data extraction (Next.js, Apollo, DOM fallback)
├── analysis/
│   ├── rules.py              # Rule-based filtering, enrichment, and value scoring
│   ├── llm.py                # LLM orchestrator — per-make analysis + synthesis
│   ├── validator.py          # Brand-bleed validation + auto-correction
│   ├── anthropic_client.py   # Anthropic API client (fallback)
│   └── ollama_client.py      # Network Ollama client (primary, optional)
├── vehicle_reference/        # Per-model markdown files auto-fed to the LLM
│   ├── honda_crv.md
│   ├── toyota_rav4.md
│   ├── kia_sportage.md
│   ├── subaru_forester.md
│   └── grand_highlander_hybrid.md
├── storage/
│   ├── csv_writer.py         # Timestamped CSV output
│   ├── history_db.py         # SQLite run history, listings, and price tracking
│   └── trends.py             # Price trend chart generation (inline HTML)
├── notifications/
│   └── email_alert.py        # Gmail API email builder and sender
├── utils/
│   ├── payment_calc.py       # Monthly payment, TCO, price-per-mile calculations
│   └── logging_config.py     # Structured logging (console + rolling file)
├── tests/
│   ├── test_urls.py
│   ├── test_payment_calc.py
│   ├── test_rules.py
│   ├── test_llm_fallback.py
│   └── test_email_highlighting.py
├── requirements.txt
├── .env.example
└── .env                      # Secrets — never commit
```

---

## Quick start

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd car_search
pip install -r requirements.txt
playwright install chromium
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```dotenv
# Required for AI analysis
ANTHROPIC_API_KEY=sk-ant-...

# Required for email (see Gmail OAuth setup below)
GMAIL_SENDER=you@gmail.com
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=          # written automatically by setup_gmail_oauth.py

EMAIL_FROM_NAME=Carvana Tracker

# Optional — network Ollama server(s) for free local LLM
# OLLAMA_NETWORK_HOST=192.168.0.100:11434
# OLLAMA_NETWORK_HOST_2=192.168.0.101:11434
```

### 3. Configure your search profile

Edit `profiles.yaml`. A minimal profile looks like:

```yaml
profiles:
  - profile_id: my_search
    label: "My SUV Search"
    vehicles:
      - [Honda, CR-V]
      - [Toyota, RAV4]
    max_price: 30000
    max_mileage: 80000
    min_year: 2021
    max_year: 2025
    fuel_type_filters: [Hybrid, Gas]
    model_preference: [CR-V, RAV4]
    email_to:
      - you@gmail.com
```

See the [profiles.yaml reference](#profilesyaml-reference) below for all options.

### 4. Set up Gmail OAuth (one time)

The tracker sends email through the Gmail API with OAuth2. You need a Google Cloud project.

**Step 1 — Create OAuth credentials:**

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → select or create a project
2. **APIs & Services → Enable APIs → search "Gmail API" → Enable**
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app**
4. Copy the **Client ID** and **Client Secret** into your `.env`

**Step 2 — Authorize the app:**

```bash
pip install google-auth-oauthlib   # one-time dependency for the setup script
python setup_gmail_oauth.py        # opens a browser, writes GMAIL_REFRESH_TOKEN to .env
```

You won't need `google-auth-oauthlib` again after this.

### 5. Add vehicle reference docs (optional but recommended)

The `vehicle_reference/` directory holds per-model markdown files that are automatically fed to the LLM when analyzing that make/model. They improve analysis quality significantly.

The tracker auto-discovers which file to use by matching the vehicle make and model in the filename. If no matching file exists for a given make/model, the LLM runs on listing data alone.

You can use the existing files as templates. Each file should cover trim hierarchy, known issues, what to look for at different price/mileage points, and hybrid vs. gas trade-offs.

### 6. Verify your setup

```bash
python main.py --check-setup
```

This tests Anthropic API access, Gmail credentials, and Ollama connectivity (if configured) without running a full scrape.

### 7. Run it

```bash
python main.py
```

---

## Usage

```bash
# Run once and exit (default)
python main.py

# Dry run — scrape and analyze but do not save or send email
python main.py --dry-run

# Skip LLM analysis (rule-based scoring only)
python main.py --no-llm

# Force a specific LLM backend
python main.py --backend api
python main.py --backend ollama

# Force email send regardless of change detection
python main.py --email

# Suppress email for this run
python main.py --no-email

# Run on a schedule (every CHECK_INTERVAL_HOURS hours)
python main.py --schedule

# Print run history, per-model stats, and pricing trends
python main.py --history

# Validate config and test all backends without scraping
python main.py --check-setup

# Show DEBUG-level output
python main.py --debug
```

---

## profiles.yaml reference

All per-search settings live in `profiles.yaml`. Multiple profiles run in a single invocation, each with its own vehicles, filters, and recipients.

```yaml
profiles:
  - profile_id: my_search          # unique slug (letters, numbers, underscores)
    label: "My SUV Search"         # shown in email subject and body

    vehicles:                      # [make, model] pairs to search
      - [Honda, CR-V]
      - [Toyota, RAV4]

    max_price: 30000               # omit or set to null for no upper limit
    max_mileage: 80000
    min_year: 2021
    max_year: 2025

    fuel_type_filters: [Hybrid, Gas]   # Hybrid | Gas | null (all fuel types).
                                       # Runs a separate Carvana search per type.
                                       # Omit to search all trims.

    model_preference: [CR-V, RAV4]     # ordered best→worst; affects sort order
                                       # and value score bonus. Omit for pure
                                       # score ranking.

    excluded_trim_keywords: [sport]    # case-insensitive substrings to drop

    show_financing: true               # show estimated monthly payments in email
    downpayment: 3000                  # overrides config.py DOWN_PAYMENT for this profile

    reference_doc_path: ./vehicle_reference/my_doc.md
    # If omitted, per-vehicle docs in vehicle_reference/ are auto-discovered
    # by matching the make/model name against filenames. Set this explicitly
    # only when you want a single combined doc for the whole profile.

    email_to:
      - you@gmail.com
      - colleague@gmail.com
```

---

## config.py reference

Global settings that apply to all profiles. Edit `config.py` directly — these are not in `.env`.

| Setting | Default | Description |
|---|---|---|
| `ZIP_CODE` | `85286` | Used by Carvana for shipping estimates |
| `DOWN_PAYMENT` | `3000` | Default down payment for monthly payment estimates |
| `INTEREST_RATE` | `7.5` | APR used in payment estimates |
| `LOAN_TERM_MONTHS` | `60` | Loan term in months |
| `CHECK_INTERVAL_HOURS` | `24` | Interval for `--schedule` mode |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Anthropic model for LLM analysis |
| `ANTHROPIC_MAX_TOKENS` | `1500` | Max tokens per LLM response |
| `OLLAMA_ENABLED` | `False` | Enable network Ollama as the primary LLM backend |
| `OLLAMA_TIMEOUT` | `600` | Seconds before an Ollama request times out |
| `OLLAMA_REF_DOC_MAX_CHARS` | `6000` | Reference doc character limit sent to Ollama |
| `MAX_PAGES_PER_SEARCH` | `5` | Carvana result pages scraped per vehicle/fuel-type |
| `SEND_EMAIL` | `True` | Send email after each run |

---

## AI analysis

### Architecture

LLM analysis runs in three phases:

1. **Per-make analysis** — One LLM call per distinct make in the results. Each call receives only that make's listings and its own reference doc, preventing brand terminology from bleeding across makes (e.g., Honda ADAS terms appearing in a Toyota analysis).

2. **Cross-model synthesis** — After all per-make calls complete, a final LLM call sees the combined listing table and a summary of each per-make analysis. It produces the top 3 picks across all makes plus a single final recommendation. This is what appears in the email body.

3. **Validation** — The synthesis output is checked for brand-bleed issues (e.g., "EyeSight" appearing in a non-Subaru context). Detected issues trigger an automatic LLM correction pass. A warning banner is injected into the email if issues remain.

### Backend selection

The tracker tries backends in this order:

1. **Ollama (network)** — Free, private, runs on a server you control. Set `OLLAMA_ENABLED = True` in `config.py` and configure `OLLAMA_NETWORK_HOST` in `.env`. If two hosts are configured, the tracker probes both at startup and routes to whichever responds faster. Supports any model loaded on the Ollama server.

2. **Anthropic API** — Higher quality output. Costs fractions of a cent per run. Requires `ANTHROPIC_API_KEY` in `.env`. Used automatically if Ollama is unavailable or disabled.

3. **None** — If both fail, the run completes without AI analysis. Scoring and email still work.

The backend used for each run is shown in the terminal output, the email footer, and the CSV `llm_backend_used` column.

### Reference docs

Per-vehicle reference docs in `vehicle_reference/` are automatically matched to each make/model by filename similarity. A doc for "Honda CR-V" would match `honda_crv.md`, `crv_reference.md`, etc.

Each reference doc can contain:

- Trim hierarchy and what each trim includes
- Known issues at specific mileage/year ranges
- Hybrid vs. gas trade-offs
- What a "good deal" looks like at the current market price

The doc is injected into the LLM prompt for the relevant make's analysis call. Reference docs for Ollama are truncated to `OLLAMA_REF_DOC_MAX_CHARS` characters; the full doc is always sent to Anthropic.

---

## Value score (0–100)

Each listing is scored before LLM analysis. Higher is better.

| Component | Weight | Logic |
|---|---|---|
| Price vs. group average | 35 | % below average price for same make/model. Capped at ±30% |
| Mileage | 25 | Inverse linear: 0 mi = 25 pts, `max_mileage` = 0 pts |
| Age | 20 | Newer = better. `max_year` = 20 pts, `min_year` = 0 pts |
| Hybrid bonus | 10 | +10 if `fuel_type_filters` includes Hybrid and trim qualifies |
| Shipping penalty | 10 | 10 pts if no shipping fee; scales to 0 at $1,500 shipping |

`model_preference` adds a tie-breaking sort on top of the raw score. Listings are displayed sorted by model preference then value score, with LLM top picks pinned to the first rows of the email table.

---

## Email summary

Each email includes:

- **Alert badges** — NEW (first-time listing) and price drop indicators with drop percentage
- **Top listings table** — LLM top picks starred (★) and pinned to the top rows; remaining slots filled by value score up to the display cap
- **Trim key** — quick-reference table of available trims for each searched model with short descriptions
- **Price trend charts** — 180-day rolling average price per model, rendered inline as HTML
- **AI analysis** — cross-model synthesis output only (per-make breakdowns are used internally but not shown in the email)

---

## Scheduling with Windows Task Scheduler

The project includes `example_run_tracker.bat` in the root to create your own Windows automation. To run it automatically every day:

1. Open **Task Scheduler** → **Create Basic Task**
2. Set the trigger to **Daily** at your preferred time
3. Set the action to run `run_tracker.bat` (edit the path inside it first)
4. Under **Settings**, check "Run task as soon as possible after a scheduled start is missed"

---

## Output files

All output is written to `carvana_results/` (gitignored):

| File | Description |
|---|---|
| `carvana_YYYYMMDD_HHMMSS_<id>.csv` | Timestamped results for each run |
| `history.db` | SQLite database with all runs, listings, and price history |
| `tracker.log` | Rolling log file (5 MB max, 3 backups) |
| `logs/run_<id>.log` | Per-run log files for debugging |

---

## Tests

```bash
python -m pytest tests/ -v
```

| Test file | Covers |
|---|---|
| `test_urls.py` | URL structure, base64 encoding, page param, fuel type filter |
| `test_payment_calc.py` | Monthly payment, TCO, price per mile, depreciation |
| `test_rules.py` | Filter removal, hybrid detection, value score boundaries |
| `test_llm_fallback.py` | Anthropic → Ollama fallback logic, both-fail case |
| `test_email_highlighting.py` | NEW badge, price drop indicators, star/top-pick logic, DB queries |

---

## Known limitations

- **Bot detection:** Carvana uses PerimeterX. Headless Chromium passes most of the time. If scraping fails consistently, residential proxies would be the next step.
- **Shipping costs:** Often not available in search results. Shown as `None` in the CSV when unavailable.
- **Synthesis table cap:** The cross-model synthesis LLM call is capped at 30 listings. For searches with many vehicles, lower-scoring listings beyond position 30 won't be eligible for the synthesis top-picks. Per-make analyses still see all listings for that make.
- **No official Carvana API:** The scraper can break if Carvana changes their frontend. The three-strategy extractor (Next.js → Apollo → DOM fallback) is designed to be resilient but may need maintenance.
- **Prices change constantly.** Each CSV row is a snapshot at scrape time.
- **Scheduler requires machine to be on.** `--schedule` mode doesn't compensate for missed runs if the machine sleeps. Use Windows Task Scheduler with `--once` for reliable execution.
