"""
Ollama local LLM client.
"""

import logging
import threading
import time

import requests

log = logging.getLogger(__name__)


class OllamaUnavailableError(Exception):
    """Raised when Ollama is unreachable or times out."""


class OllamaModelError(Exception):
    """Raised when the configured model is not found on the Ollama server."""


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.model    = model
        self.timeout  = timeout

    def is_available(self) -> bool:
        """
        GET {base_url}/api/tags — returns True if Ollama is running and
        the configured model is in the response. Returns False on any exception.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            available = any(self.model in m for m in models)
            log.debug(
                "Ollama is_available=%s (model=%s, found=%s)",
                available, self.model, models,
            )
            return available
        except Exception as exc:
            log.debug("Ollama is_available check failed: %s", exc)
            return False

    def warmup(self) -> None:
        """
        Fire a trivial request to load the model into RAM without blocking the caller.
        Intended to be called at run start so the model is warm by the time
        real analysis begins.  Errors are silently logged — warmup failure is not fatal.
        """
        if not self.is_available():
            log.debug("Ollama warmup skipped — server not available")
            return

        def _send() -> None:
            try:
                log.info("Ollama warmup: loading %s into RAM…", self.model)
                resp = requests.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": "Hi", "stream": False},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                log.info("Ollama warmup complete (%s ready)", self.model)
            except Exception as exc:
                log.debug("Ollama warmup failed (non-fatal): %s", exc)

        thread = threading.Thread(target=_send, daemon=True, name="ollama-warmup")
        thread.start()

    def analyze(self, prompt: str, reference_doc: str = "") -> str:
        """
        POST to {base_url}/api/generate with stream=False.
        Returns the response text.
        Raises OllamaUnavailableError on connection failure or timeout.
        Raises OllamaModelError if model not found (HTTP 404).

        If reference_doc is non-empty it is prepended to the prompt under a
        [REFERENCE DOCUMENT] / [TASK] structure so the model has vehicle
        knowledge context before seeing the listings data.
        """
        if reference_doc:
            prompt = f"[REFERENCE DOCUMENT]\n{reference_doc}\n\n[TASK]\n{prompt}"

        payload = {
            "model":  self.model,
            "prompt": prompt,
            "stream": False,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise OllamaUnavailableError(f"Ollama request timed out after {self.timeout}s") from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailableError(f"Cannot connect to Ollama at {self.base_url}") from exc

        if resp.status_code == 404:
            raise OllamaModelError(f"Model '{self.model}' not found on Ollama server")
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise OllamaUnavailableError(f"Ollama returned HTTP {resp.status_code}") from exc

        return resp.json().get("response", "")
