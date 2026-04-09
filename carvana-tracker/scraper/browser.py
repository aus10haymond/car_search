"""
Playwright browser lifecycle management.

One browser instance is created per scraper run and reused across all
vehicle searches. Call get_page_content() for each URL, then close()
when done. Use as a context manager to ensure cleanup.
"""

import logging
import time

import config

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class Browser:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_kwargs = {"headless": config.HEADLESS}
        if config.PROXY_URL:
            launch_kwargs["proxy"] = {"server": config.PROXY_URL}

        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        log.debug("Browser started (headless=%s)", config.HEADLESS)

    def get_page_content(self, url: str) -> str:
        """
        Load `url` and return raw HTML after network is idle.
        Returns empty string on TimeoutError; does not raise.
        """
        from playwright.sync_api import TimeoutError as PWTimeout

        page = self._context.new_page()
        try:
            page.goto(
                url,
                wait_until="load",
                timeout=config.PAGE_TIMEOUT_SECONDS * 1000,
            )
            # Give React/Next.js time to hydrate after initial load
            time.sleep(3)
            html = page.content()
            log.debug("Loaded %s (%d bytes)", url, len(html))
            return html
        except PWTimeout:
            log.warning("Timeout loading %s — skipping", url)
            return ""
        except Exception as exc:
            log.warning("Error loading %s: %s", url, exc)
            return ""
        finally:
            page.close()
            time.sleep(config.REQUEST_DELAY_SECONDS)

    def close(self) -> None:
        try:
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
