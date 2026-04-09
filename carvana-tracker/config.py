import os
from dotenv import load_dotenv

load_dotenv()

# ── Vehicles ──────────────────────────────────────────────────────────────────
VEHICLES = [
    # (make, model, min_year, max_year)
    ("Honda",  "CR-V",     2021, 2025),
    ("Toyota", "RAV4",     2021, 2025),
    ("Subaru", "Forester", 2021, 2025),
    ("Kia",    "Sportage", 2023, 2025),
]

# ── Filters ───────────────────────────────────────────────────────────────────
MAX_PRICE    = 30000
MAX_MILEAGE  = 80000
MIN_YEAR     = 2021
MAX_YEAR     = 2025
# Set to "Hybrid" to filter Carvana search results to hybrid vehicles only.
# Set to None to include all fuel types (gas + hybrid).
# List of fuel type searches to run per vehicle. Each entry triggers a separate
# Carvana search. Results are merged and deduplicated by VIN.
# Use [] or [None] for a single unfiltered search.
# Carvana values: "Hybrid", "Gas" (or try "Gasoline" if Gas yields nothing)
FUEL_TYPE_FILTERS: list[str | None] = ["Hybrid", "Gas"]

# ── Location ──────────────────────────────────────────────────────────────────
ZIP_CODE = "85286"   # Phoenix, AZ — used by Carvana for shipping estimates

# ── Payment calculator ────────────────────────────────────────────────────────
DOWN_PAYMENT     = 3000    # dollars
INTEREST_RATE    = 7.5     # APR percent
LOAN_TERM_MONTHS = 60

# ── Scheduling ────────────────────────────────────────────────────────────────
CHECK_INTERVAL_HOURS = 24

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "./carvana_results"
DB_PATH    = "./carvana_results/history.db"
LOG_FILE   = "./carvana_results/tracker.log"

# ── AI analysis ───────────────────────────────────────────────────────────────
REFERENCE_DOC_PATH = "./SUV_REFERENCE_CONTEXT.md"

# Primary: Anthropic API
ANTHROPIC_ENABLED    = True
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL      = "claude-haiku-4-5-20251001"
ANTHROPIC_MAX_TOKENS = 1500

# Fallback: local Ollama
OLLAMA_ENABLED  = True
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "gemma3:4b"
OLLAMA_TIMEOUT  = 300               # seconds

# ── Alerts ────────────────────────────────────────────────────────────────────
ALERT_PRICE_THRESHOLD = 30000
ALERT_HYBRID_ONLY     = False

# ── Email — Mailjet (optional) ────────────────────────────────────────────────
SEND_EMAIL          = True
EMAIL_FROM          = os.getenv("EMAIL_FROM", "")           # Verified sender address
EMAIL_FROM_NAME     = os.getenv("EMAIL_FROM_NAME", "Carvana Tracker")
# Comma-separated list of recipient addresses, e.g. "a@gmail.com,b@gmail.com"
EMAIL_TO            = [a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()]
MAILJET_API_KEY     = os.getenv("MAILJET_API_KEY", "")
MAILJET_SECRET_KEY  = os.getenv("MAILJET_SECRET_KEY", "")

# ── Scraping behaviour ────────────────────────────────────────────────────────
HEADLESS              = True
REQUEST_DELAY_SECONDS = 4
PAGE_TIMEOUT_SECONDS  = 30
MAX_PAGES_PER_SEARCH  = 5
PROXY_URL             = ""  # Stub for future residential proxy support
