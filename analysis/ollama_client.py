"""
Ollama local LLM client.
"""

import logging

import requests

log = logging.getLogger(__name__)


class OllamaUnavailableError(Exception):
    """Raised when Ollama is unreachable or times out."""


class OllamaModelError(Exception):
    """Raised when the configured model is not found on the Ollama server."""


class OllamaClient:
    def __init__(self, base_url: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout

    def is_available(self) -> bool:
        """
        GET {base_url}/api/tags — returns True if the Ollama server is reachable.
        Does not check for a specific model.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            log.debug("Ollama is_available=True at %s", self.base_url)
            return True
        except Exception as exc:
            log.debug("Ollama is_available check failed: %s", exc)
            return False

    def get_preferred_model(self, preferred: list[str]) -> str | None:
        """
        Returns the first model from `preferred` that is installed on the server,
        or None if none match or the server is unreachable.
        Matching is exact on the full name (e.g. "qwen3.5:9b").
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            installed = {m.get("name", "") for m in resp.json().get("models", [])}
            for model in preferred:
                if model in installed:
                    log.debug("Ollama preferred model selected: %s", model)
                    return model
            log.debug("Ollama: none of the preferred models are installed (installed=%s)", installed)
            return None
        except Exception as exc:
            log.debug("Ollama get_preferred_model failed: %s", exc)
            return None

    def get_loaded_model(self) -> str | None:
        """
        GET {base_url}/api/ps — returns the name of the currently loaded model,
        or None if no model is loaded or the server is unreachable.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/ps", timeout=5)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            if models:
                name = models[0].get("name", "")
                log.debug("Ollama loaded model: %s", name)
                return name or None
            log.debug("Ollama: no model currently loaded")
            return None
        except Exception as exc:
            log.debug("Ollama get_loaded_model failed: %s", exc)
            return None

    def warm_up(self, preferred_models: list[str]) -> str | None:
        """
        Ensure a model is loaded and ready before the main analysis runs.

        1. If a model is already loaded, return its name immediately.
        2. Otherwise find the first preferred model that is installed and send
           a short prompt to force Ollama to load it into memory.

        Returns the loaded model name on success, or None if Ollama is
        unreachable, no preferred model is installed, or the load times out.
        Never raises.
        """
        # Fast path — model already in memory
        loaded = self.get_loaded_model()
        if loaded:
            log.info("Ollama warm-up: model already loaded (%s) — skipping", loaded)
            return loaded

        model = self.get_preferred_model(preferred_models)
        if not model:
            log.warning("Ollama warm-up: no preferred model installed — skipping")
            return None

        log.info(
            "Ollama warm-up: no model loaded — sending ping to load %s "
            "(timeout=%ss, this may take a moment)…",
            model, self.timeout,
        )
        try:
            self.analyze("Reply with only the word OK.", model=model)
            log.info("Ollama warm-up complete — %s is loaded and ready", model)
            return model
        except (OllamaUnavailableError, OllamaModelError) as exc:
            log.warning("Ollama warm-up failed: %s", exc)
            return None

    def analyze(self, prompt: str, reference_doc: str = "", model: str = "") -> str:
        """
        POST to {base_url}/api/generate with stream=False.
        Returns the response text.
        Raises OllamaUnavailableError on connection failure or timeout.
        Raises OllamaModelError if model not found (HTTP 404).

        `model` must be provided — call get_loaded_model() first to obtain it.

        If reference_doc is non-empty it is prepended to the prompt under a
        [REFERENCE DOCUMENT] / [TASK] structure so the model has vehicle
        knowledge context before seeing the listings data.
        """
        if not model:
            raise OllamaModelError("No model specified for analyze() call")
        if reference_doc:
            prompt = f"[REFERENCE DOCUMENT]\n{reference_doc}\n\n[TASK]\n{prompt}"

        payload = {
            "model":  model,
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
            raise OllamaModelError(f"Model '{model}' not found on Ollama server")
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise OllamaUnavailableError(f"Ollama returned HTTP {resp.status_code}") from exc

        return resp.json().get("response", "")

