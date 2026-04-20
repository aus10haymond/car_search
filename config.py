import os
from dotenv import load_dotenv

load_dotenv()

# Load user-configurable settings from dashboard_settings.json.
# All existing imports (import config; config.DOWN_PAYMENT) continue to work
# unchanged — this file still exposes every value as a module-level attribute.
from dashboard.backend.settings_store import load as _load_settings
_s = _load_settings()

# ── Location ──────────────────────────────────────────────────────────────────
ZIP_CODE: str = _s["zip_code"]

# ── Payment calculator ────────────────────────────────────────────────────────
DOWN_PAYMENT:     int   = _s["down_payment"]
INTEREST_RATE:    float = _s["interest_rate"]
LOAN_TERM_MONTHS: int   = _s["loan_term_months"]

# ── Scheduling ────────────────────────────────────────────────────────────────
CHECK_INTERVAL_HOURS: int = _s["check_interval_hours"]

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR:            str = _s["output_dir"]
VEHICLE_REFERENCE_DIR: str = _s["vehicle_reference_dir"]
DB_PATH:               str = _s["db_path"]
LOG_FILE:              str = _s["log_file"]

# ── AI analysis — Ollama ──────────────────────────────────────────────────────
# Primary: Network Ollama (uses whatever model is currently loaded)
OLLAMA_ENABLED:          bool      = _s["ollama_enabled"]
OLLAMA_NETWORK_HOST:     str       = os.getenv("OLLAMA_NETWORK_HOST", "")
OLLAMA_NETWORK_HOST_2:   str       = os.getenv("OLLAMA_NETWORK_HOST_2", "")
# Active server URL — overwritten at startup by select_best_server() when
# multiple hosts are configured.
OLLAMA_NETWORK_BASE_URL: str       = f"http://{OLLAMA_NETWORK_HOST}" if OLLAMA_NETWORK_HOST else ""
# All configured Ollama server URLs (used for server selection at startup).
OLLAMA_NETWORK_HOSTS: list[str] = [
    url for url in [
        f"http://{OLLAMA_NETWORK_HOST}"   if OLLAMA_NETWORK_HOST   else "",
        f"http://{OLLAMA_NETWORK_HOST_2}" if OLLAMA_NETWORK_HOST_2 else "",
    ]
    if url
]
OLLAMA_TIMEOUT:           int       = _s["ollama_timeout"]
# Reference doc is truncated to this length before being sent to Ollama.
# Local 9B models are slow at evaluating large contexts; the full doc is
# still sent to Anthropic which handles large contexts without issue.
# Set to 0 to disable truncation (not recommended for large reference docs).
OLLAMA_REF_DOC_MAX_CHARS: int       = _s["ollama_ref_doc_max_chars"]
# If no model is loaded, the first model from this list that is installed on the
# server will be loaded. Order by preference (best instruction-follower first).
OLLAMA_PREFERRED_MODELS: list[str]  = _s["ollama_preferred_models"]

# ── AI analysis — Anthropic API ───────────────────────────────────────────────
# Fallback: Anthropic API
ANTHROPIC_ENABLED:    bool = _s["anthropic_enabled"]
ANTHROPIC_API_KEY:    str  = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL:      str  = _s["anthropic_model"]
ANTHROPIC_MAX_TOKENS: int  = _s["anthropic_max_tokens"]

# ── Email — Gmail API (optional) ─────────────────────────────────────────────
# Recipients are configured per-profile in profiles.yaml.
# Run  python setup_gmail_oauth.py  once to populate the three OAuth values.
SEND_EMAIL:          bool = _s["send_email"]
EMAIL_FROM_NAME:     str  = os.getenv("EMAIL_FROM_NAME", "Carvana Tracker")
GMAIL_SENDER:        str  = os.getenv("GMAIL_SENDER", "")
GMAIL_CLIENT_ID:     str  = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET: str  = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN: str  = os.getenv("GMAIL_REFRESH_TOKEN", "")

# ── Scraping behaviour ────────────────────────────────────────────────────────
HEADLESS:              bool = _s["headless"]
REQUEST_DELAY_SECONDS: int  = _s["request_delay_seconds"]
PAGE_TIMEOUT_SECONDS:  int  = _s["page_timeout_seconds"]
MAX_PAGES_PER_SEARCH:  int  = _s["max_pages_per_search"]
PROXY_URL:             str  = ""  # Stub for future residential proxy support
