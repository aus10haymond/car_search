# Carvana SUV Tracker

Scheduled Python tool that scrapes Carvana for used SUVs, scores and filters listings, runs AI analysis via a local Ollama model (with Anthropic API fallback), and sends an HTML email summary with price trend charts.

---

## What it does

Each run:
1. Scrapes Carvana for Honda CR-V, Toyota RAV4, Subaru Forester, and Kia Sportage
2. Filters by price, mileage, and year
3. Scores each listing 0–100 based on price vs. group average, mileage, age, hybrid status, and shipping
4. Runs AI analysis on the top listings using Ollama (local) or the Anthropic API (fallback)
5. Saves results to a timestamped CSV and a SQLite history database
6. Sends an HTML email with alerts, a top-20 table, price trend charts, and AI analysis

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Install and start Ollama (optional but recommended)

Download from [ollama.com](https://ollama.com), then:

```bash
ollama pull gemma3:4b
ollama serve
```

The tracker pre-warms the model at run start so it's ready by the time analysis runs.

### 3. Configure

Edit `config.py` to set your preferences (vehicles, price/mileage limits, ZIP code, loan terms, etc.).

Create a `.env` file in the `carvana-tracker/` directory with your secrets:

```
# Email sending via Mailjet (https://mailjet.com — free tier works)
MAILJET_API_KEY=your_api_key
MAILJET_SECRET_KEY=your_secret_key
EMAIL_FROM=you@example.com
EMAIL_FROM_NAME=Carvana Tracker
EMAIL_TO=you@example.com,partner@example.com

# Anthropic API fallback (optional)
ANTHROPIC_API_KEY=sk-ant-...
```

See `.env.example` for all available keys.

### 4. Verify setup

```bash
python main.py --check-setup
```

This tests Ollama connectivity, the Anthropic API key, and Mailjet credentials without running a full scrape.

---

## Usage

```bash
# Run once and exit
python main.py --once

# Run on a schedule (every CHECK_INTERVAL_HOURS hours)
python main.py --schedule

# Dry run — scrape and analyze but do not save or send email
python main.py --dry-run

# Skip LLM analysis (rules-based scoring only)
python main.py --no-llm

# Force a specific LLM backend
python main.py --backend ollama
python main.py --backend api

# Force email send regardless of config
python main.py --email

# Suppress email for this run
python main.py --no-email

# Print run history from the database
python main.py --history

# Validate config and test all backends
python main.py --check-setup
```

---

## Configuration reference

All settings live in `config.py`. Secrets load from `.env` via python-dotenv.

| Setting | Default | Description |
|---|---|---|
| `VEHICLES` | 4 SUV models | List of `(make, model, min_year, max_year)` tuples to search |
| `MAX_PRICE` | 30000 | Filter out listings above this price |
| `MAX_MILEAGE` | 80000 | Filter out listings above this mileage |
| `MIN_YEAR` / `MAX_YEAR` | 2021 / 2025 | Year range filter |
| `ZIP_CODE` | 85286 | Used by Carvana to calculate shipping estimates |
| `DOWN_PAYMENT` | 3000 | Down payment used in monthly payment estimates |
| `INTEREST_RATE` | 7.5 | APR used in monthly payment estimates |
| `LOAN_TERM_MONTHS` | 60 | Loan term in months |
| `CHECK_INTERVAL_HOURS` | 24 | How often to run in `--schedule` mode |
| `ALERT_PRICE_THRESHOLD` | 30000 | Send email alert if any listing falls below this price |
| `OLLAMA_ENABLED` | True | Enable local Ollama LLM |
| `OLLAMA_MODEL` | gemma3:4b | Ollama model to use |
| `OLLAMA_TIMEOUT` | 300 | Seconds before Ollama request times out |
| `ANTHROPIC_ENABLED` | False | Enable Anthropic API as fallback |
| `ANTHROPIC_MODEL` | claude-haiku-4-5-20251001 | Anthropic model to use |
| `SEND_EMAIL` | True | Send email summary after each run |
| `MAX_PAGES_PER_SEARCH` | 5 | Maximum Carvana result pages to scrape per vehicle |

---

## Scheduling with Windows Task Scheduler

To run the tracker automatically every day:

1. Create `run_tracker.bat` in the `carvana-tracker/` directory:
   ```bat
   @echo off
   cd /d C:\path\to\car_search\carvana-tracker
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
|---|---|
| `carvana_YYYYMMDD_HHMMSS.csv` | Timestamped results for each run |
| `carvana_latest.csv` | Always overwritten with the most recent run |
| `history.db` | SQLite database tracking all runs, listings, and price history |
| `tracker.log` | Rolling log file (5 MB max, 3 backups) |
| `logs/run_*.log` | Per-run log files for debugging |

---

## Value score (0–100)

Each listing is scored before LLM analysis. Higher is better.

| Component | Weight | Logic |
|---|---|---|
| Price vs. group average | 35 | % below average price for same make/model. Capped at ±30% |
| Mileage | 25 | Inverse linear: 0 mi = 25 pts, 80,000 mi = 0 pts |
| Age | 20 | Newer = better. 2025 = 20 pts, 2021 = 0 pts |
| Hybrid bonus | 10 | +10 if trim contains "hybrid", "hev", "phev", or "prime" |
| Shipping penalty | 10 | 10 pts if no shipping fee; scales to 0 at $1,500 shipping |

---

## AI analysis

The tracker tries backends in this order:

1. **Ollama (local)** — free, private, runs on your machine. gemma3:4b is a good balance of speed and quality. The model is pre-warmed in a background thread at run start to avoid cold-start timeouts.
2. **Anthropic API** — higher quality, costs fractions of a cent per run. Set `ANTHROPIC_ENABLED = True` and provide your API key.
3. **None** — if both fail, the run completes without AI analysis. Scoring and email still work.

Which backend was used is always shown in the terminal output, email footer, and CSV `llm_backend_used` column.

---

## Tests

```bash
python -m pytest tests/ -v
```

| Test file | Covers |
|---|---|
| `test_urls.py` | URL structure, base64 encoding, page param |
| `test_payment_calc.py` | Monthly payment, TCO, price per mile, depreciation |
| `test_rules.py` | Filter removal, hybrid detection, value score boundaries |
| `test_llm_fallback.py` | Ollama→API fallback logic, both-fail case |

---

## Known limitations

- **Bot detection:** Carvana uses PerimeterX. Headless Chromium passes most of the time. If scraping starts failing consistently, residential proxies would be the next step (out of scope).
- **Shipping costs:** Often not available in search results. Shown as "N/A" when unavailable — not treated as $0.
- **Ollama cold starts:** First run after machine restart can be slow. The pre-warmup mitigates this but requires Ollama to already be running.
- **No official API:** Carvana doesn't provide a public API. The scraper can break if Carvana changes their frontend. The schema.org ld+json strategy is the most stable but is not guaranteed.
- **Prices change constantly.** Each CSV row is a snapshot at scrape time.
