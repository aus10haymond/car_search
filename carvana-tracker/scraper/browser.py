"""
Playwright browser lifecycle management.

One browser instance is created per scraper run and reused across all
vehicle searches. Call get_page_content() for each URL, then close()
when done. Use as a context manager to ensure cleanup.
"""

import logging
import time
from typing import Any

import config

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class Browser:
    def __init__(self):
        self._playwright: Any = None
        self._browser:    Any = None
        self._context:    Any = None
        self._page:       Any = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": config.HEADLESS}
        if config.PROXY_URL:
            launch_kwargs["proxy"] = {"server": config.PROXY_URL}

        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._new_context()
        log.debug("Browser started (headless=%s)", config.HEADLESS)

    def _new_context(self) -> None:
        """Create (or replace) the browser context and a single reusable page."""
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        self._context = self._browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        self._page = self._context.new_page()
        log.debug("Fresh browser context created")

    def reset_context(self) -> None:
        """
        Drop the current context and open a new one.
        Call between vehicle searches to clear Carvana session/cookies
        and reduce bot-detection risk.
        """
        self._new_context()
        log.debug("Browser context reset")

    def get_page_content(self, url: str) -> str:
        """
        Navigate the persistent page to `url` and return raw HTML.
        Reusing the same page across pagination preserves referrer headers
        and browser state, avoiding bot detection on page 2+.
        Returns empty string on TimeoutError; does not raise.
        """
        from playwright.sync_api import TimeoutError as PWTimeout

        try:
            self._page.goto(
                url,
                wait_until="load",
                timeout=config.PAGE_TIMEOUT_SECONDS * 1000,
            )
            # Wait for listing content to appear — handles pages where results
            # are injected dynamically after the initial HTML load.
            try:
                self._page.wait_for_selector(
                    'script[type="application/ld+json"], [data-qa="vehicle-card"], [class*="VehicleCard"]',
                    timeout=8000,
                )
            except Exception:
                pass  # No vehicle elements found; extraction will handle it

            final_url = self._page.url
            if final_url != url:
                log.info("Redirected: %s → %s", url, final_url)

            html = self._page.content()
            log.info("Loaded %s (%d bytes)", url, len(html))
            return html
        except PWTimeout:
            log.warning("Timeout loading %s — skipping", url)
            return ""
        except Exception as exc:
            log.warning("Error loading %s: %s", url, exc)
            return ""
        finally:
            time.sleep(config.REQUEST_DELAY_SECONDS)

    def close(self) -> None:
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
            log.debug("Browser closed")
        except Exception as exc:
            log.warning("Error closing browser: %s", exc)

    # ── context manager support ───────────────────────────────────────────────

    def __enter__(self) -> "Browser":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.close()
