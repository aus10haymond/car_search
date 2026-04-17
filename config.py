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
OUTPUT_DIR            = "./carvana_results"
VEHICLE_REFERENCE_DIR = "./vehicle_reference"  # per-model reference docs for auto-discovery
DB_PATH    = "./carvana_results/history.db"
LOG_FILE   = "./carvana_results/tracker.log"

# ── AI analysis ───────────────────────────────────────────────────────────────
# Reference doc is set per-profile in profiles.yaml via reference_doc_path.

# Primary: Network Ollama (uses whatever model is currently loaded)
OLLAMA_ENABLED           = False
OLLAMA_NETWORK_HOST      = os.getenv("OLLAMA_NETWORK_HOST", "")
OLLAMA_NETWORK_HOST_2    = os.getenv("OLLAMA_NETWORK_HOST_2", "")
# Active server URL — overwritten at startup by select_best_server() when
# multiple hosts are configured.
OLLAMA_NETWORK_BASE_URL  = f"http://{OLLAMA_NETWORK_HOST}" if OLLAMA_NETWORK_HOST else ""
# All configured Ollama server URLs (used for server selection at startup).
OLLAMA_NETWORK_HOSTS: list[str] = [
    url for url in [
        f"http://{OLLAMA_NETWORK_HOST}"   if OLLAMA_NETWORK_HOST   else "",
        f"http://{OLLAMA_NETWORK_HOST_2}" if OLLAMA_NETWORK_HOST_2 else "",
    ]
    if url
]
OLLAMA_TIMEOUT           = 600              # seconds (10 min max before Anthropic fallback)
# Reference doc is truncated to this length before being sent to Ollama.
# Local 9B models are slow at evaluating large contexts; the full doc is
# still sent to Anthropic which handles large contexts without issue.
# Set to 0 to disable truncation (not recommended for large reference docs).
OLLAMA_REF_DOC_MAX_CHARS = 6000

# If no model is loaded, the first model from this list that is installed on the
# server will be loaded. Order by preference (best instruction-follower first).
OLLAMA_PREFERRED_MODELS = [
    "qwen3.5:9b",
    "deepseek-r1:latest",
    "gemma4:e4b",
    "qwen3.5:4b",
    "gemma4:e2b",
]

# Fallback: Anthropic API
ANTHROPIC_ENABLED    = True
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL      = "claude-haiku-4-5-20251001"
ANTHROPIC_MAX_TOKENS = 1500

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
