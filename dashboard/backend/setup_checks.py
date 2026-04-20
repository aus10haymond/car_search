"""
Programmatic setup / health checks.

Returns structured dicts instead of printing to stdout so the FastAPI
setup router can expose the same results over HTTP.

The existing check_setup() in main.py calls run_setup_checks() and formats
the output for CLI display — nothing else in the codebase needs to change.
"""

from pathlib import Path


def run_setup_checks() -> dict:
    """
    Run all health checks and return a structured result dict.

    Keys: "profiles", "ollama", "anthropic", "gmail", "playwright"
    Each value is a dict with at minimum a "status" key:
        "ok" | "warning" | "error" | "not_configured"
    """
    import config  # imported here to avoid circular import at module level

    results: dict = {}

    # ── Profiles ──────────────────────────────────────────────────────────────
    try:
        from profiles import load_profiles
        profiles = load_profiles("profiles.yaml")
        results["profiles"] = {"status": "ok", "count": len(profiles)}
    except Exception as exc:
        results["profiles"] = {"status": "error", "detail": str(exc)}

    # ── Ollama ────────────────────────────────────────────────────────────────
    from analysis.ollama_client import OllamaClient
    if config.OLLAMA_NETWORK_BASE_URL:
        try:
            ollama = OllamaClient(config.OLLAMA_NETWORK_BASE_URL, timeout=5)
            loaded = ollama.get_loaded_model()
            if loaded:
                results["ollama"] = {
                    "status": "ok",
                    "host": config.OLLAMA_NETWORK_HOST,
                    "loaded_model": loaded,
                }
            elif ollama.is_available():
                results["ollama"] = {
                    "status": "warning",
                    "host": config.OLLAMA_NETWORK_HOST,
                    "detail": "reachable but no model loaded — will fall back to Anthropic",
                }
            else:
                results["ollama"] = {
                    "status": "error",
                    "host": config.OLLAMA_NETWORK_HOST,
                    "detail": "not reachable",
                }
        except Exception as exc:
            results["ollama"] = {
                "status": "error",
                "host": config.OLLAMA_NETWORK_HOST,
                "detail": str(exc),
            }
    else:
        results["ollama"] = {
            "status": "not_configured",
            "detail": "OLLAMA_NETWORK_HOST not set in .env",
        }

    # ── Anthropic API ─────────────────────────────────────────────────────────
    from analysis.anthropic_client import AnthropicClient, AnthropicUnavailableError
    anthropic = AnthropicClient(
        config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL, max_tokens=10,
    )
    if not anthropic.is_configured():
        results["anthropic"] = {
            "status": "not_configured",
            "detail": "ANTHROPIC_API_KEY not set in .env",
        }
    else:
        try:
            anthropic.analyze("Reply with only the word OK.")
            results["anthropic"] = {
                "status": "ok",
                "model": config.ANTHROPIC_MODEL,
            }
        except AnthropicUnavailableError as exc:
            results["anthropic"] = {
                "status": "error",
                "model": config.ANTHROPIC_MODEL,
                "detail": str(exc),
            }

    # ── Gmail ─────────────────────────────────────────────────────────────────
    gmail_ready = bool(
        config.GMAIL_CLIENT_ID
        and config.GMAIL_CLIENT_SECRET
        and config.GMAIL_REFRESH_TOKEN
        and config.GMAIL_SENDER
    )
    if gmail_ready:
        results["gmail"] = {
            "status": "ok",
            "sender": config.GMAIL_SENDER,
        }
    else:
        missing = [
            name for name, val in [
                ("GMAIL_CLIENT_ID",     config.GMAIL_CLIENT_ID),
                ("GMAIL_CLIENT_SECRET", config.GMAIL_CLIENT_SECRET),
                ("GMAIL_REFRESH_TOKEN", config.GMAIL_REFRESH_TOKEN),
                ("GMAIL_SENDER",        config.GMAIL_SENDER),
            ]
            if not val
        ]
        results["gmail"] = {
            "status": "not_configured",
            "detail": f"Missing: {', '.join(missing)}",
        }

    # ── Playwright / Chromium ─────────────────────────────────────────────────
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser_path = p.chromium.executable_path
            if Path(browser_path).exists():
                results["playwright"] = {
                    "status": "ok",
                    "chromium_path": browser_path,
                }
            else:
                results["playwright"] = {
                    "status": "error",
                    "detail": "Chromium binary not found — run: playwright install chromium",
                }
    except Exception as exc:
        results["playwright"] = {
            "status": "error",
            "detail": str(exc),
        }

    return results
