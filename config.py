import os
from dotenv import load_dotenv

load_dotenv()

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
# Reference doc is set per-profile in profiles.yaml via reference_doc_path.

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

# ── Email — Gmail API (optional) ─────────────────────────────────────────────
# Recipients are configured per-profile in profiles.yaml.
# Run  python setup_gmail_oauth.py  once to populate the three OAuth values.
SEND_EMAIL            = True
EMAIL_FROM_NAME       = os.getenv("EMAIL_FROM_NAME", "Carvana Tracker")
GMAIL_SENDER          = os.getenv("GMAIL_SENDER", "")           # your Gmail address
GMAIL_CLIENT_ID       = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET   = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN   = os.getenv("GMAIL_REFRESH_TOKEN", "")

# ── Scraping behaviour ────────────────────────────────────────────────────────
HEADLESS              = True
REQUEST_DELAY_SECONDS = 4
PAGE_TIMEOUT_SECONDS  = 30
MAX_PAGES_PER_SEARCH  = 5
PROXY_URL             = ""  # Stub for future residential proxy support
