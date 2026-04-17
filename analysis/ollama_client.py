"""
Ollama local LLM client.
"""

import concurrent.futures
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


# ── Multi-server selection ────────────────────────────────────────────────────

def _probe_server(base_url: str, preferred_models: list[str]) -> dict | None:
    """
    Query a single Ollama server and return a summary dict, or None if
    the server is unreachable.

    Returned keys:
      base_url            — the server's base URL
      loaded_model        — name of the currently loaded model, or None
      preferred_loaded    — True if loaded_model is in preferred_models
      preferred_installed — first preferred model that is installed, or None
    """
    url = base_url.rstrip("/")
    try:
        r_ps = requests.get(f"{url}/api/ps", timeout=5)
        r_ps.raise_for_status()
        loaded_names = [m.get("name", "") for m in r_ps.json().get("models", [])]
        loaded_model = loaded_names[0] if loaded_names else None

        r_tags = requests.get(f"{url}/api/tags", timeout=5)
        r_tags.raise_for_status()
        installed = {m.get("name", "") for m in r_tags.json().get("models", [])}

        preferred_loaded    = bool(loaded_model and loaded_model in preferred_models)
        preferred_installed = next((m for m in preferred_models if m in installed), None)

        return {
            "base_url":            url,
            "loaded_model":        loaded_model,
            "preferred_loaded":    preferred_loaded,
            "preferred_installed": preferred_installed,
        }
    except Exception as exc:
        log.debug("Ollama probe failed for %s: %s", base_url, exc)
        return None


def _benchmark_server(base_url: str, model: str, timeout: int) -> float | None:
    """
    Run a short capped generation and return tokens/second, or None on failure.
    Uses num_predict=20 so the call completes quickly even on slower hardware.
    """
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={
                "model":   model,
                "prompt":  "List five colors.",
                "stream":  False,
                "options": {"num_predict": 20},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data       = resp.json()
        eval_count = data.get("eval_count", 0)
        eval_ns    = data.get("eval_duration", 0)
        if eval_count > 0 and eval_ns > 0:
            return eval_count / (eval_ns / 1e9)
    except Exception as exc:
        log.debug("Ollama benchmark failed for %s (%s): %s", base_url, model, exc)
    return None


def select_best_server(
    base_urls: list[str],
    preferred_models: list[str],
    benchmark_timeout: int = 45,
) -> str | None:
    """
    Probe all Ollama servers in parallel and return the base URL of the best one.

    Selection tiers (highest wins without benchmarking):
      Tier 1 — server has a preferred model already loaded in VRAM
      Tier 2 — server has a preferred model installed (best rank wins)
      Tier 3 — any reachable server

    When multiple servers share the top tier, a short generation benchmark
    (20 tokens) is run on each in parallel and the fastest (tok/s) wins.
    Tier-2 ties are broken by preferred-model rank instead of benchmarking
    (avoids waiting for model loads just to pick a server).

    Returns None if no servers respond.
    """
    if not base_urls:
        return None

    log.info("Probing %d Ollama server(s)...", len(base_urls))

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(base_urls)) as ex:
        futures = {ex.submit(_probe_server, url, preferred_models): url for url in base_urls}
        servers = [f.result() for f in concurrent.futures.as_completed(futures)]
    servers = [s for s in servers if s is not None]

    if not servers:
        log.warning("No Ollama servers reachable")
        return None

    # Log what each server reported
    for s in servers:
        loaded_str = s["loaded_model"] or "nothing loaded"
        if s["preferred_loaded"]:
            status = "preferred model loaded"
        elif s["preferred_installed"]:
            status = f"preferred installed ({s['preferred_installed']})"
        else:
            status = "no preferred model"
        log.info("  %s - %s [%s]", s["base_url"], loaded_str, status)

    if len(servers) == 1:
        log.info("Only one server reachable → %s", servers[0]["base_url"])
        return servers[0]["base_url"]

    # ── Tier the candidates ───────────────────────────────────────────────────
    tier1 = [s for s in servers if s["preferred_loaded"]]
    tier2 = [s for s in servers if not s["preferred_loaded"] and s["preferred_installed"]]
    candidates = tier1 or tier2 or servers

    if len(candidates) == 1:
        log.info("Selected Ollama server: %s (sole tier candidate)", candidates[0]["base_url"])
        return candidates[0]["base_url"]

    # Tier-2 tie: rank by preferred-model order (no benchmark — model isn't loaded yet)
    if not tier1 and tier2:
        def _rank(s: dict) -> int:
            try:
                return preferred_models.index(s["preferred_installed"])
            except ValueError:
                return len(preferred_models)
        best = min(tier2, key=_rank)
        log.info(
            "Selected Ollama server: %s (best preferred model: %s)",
            best["base_url"], best["preferred_installed"],
        )
        return best["base_url"]

    # Tier-1 or tier-3 tie: benchmark in parallel
    log.info("Benchmarking %d server(s) (20-token generation)...", len(candidates))

    def _bench(s: dict) -> tuple[dict, float | None]:
        model = s["loaded_model"] or s["preferred_installed"]
        if not model:
            return s, None
        tps = _benchmark_server(s["base_url"], model, timeout=benchmark_timeout)
        return s, tps

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as ex:
        bench_results = list(ex.map(_bench, candidates))

    best_server, best_tps = None, -1.0
    for s, tps in bench_results:
        tps_str = f"{tps:.1f} tok/s" if tps is not None else "benchmark failed"
        log.info("  %s: %s", s["base_url"], tps_str)
        if tps is not None and tps > best_tps:
            best_tps, best_server = tps, s

    if best_server:
        log.info(
            "Selected Ollama server: %s (%.1f tok/s)",
            best_server["base_url"], best_tps,
        )
        return best_server["base_url"]

    # All benchmarks failed — fall back to first reachable candidate
    log.warning(
        "All benchmarks failed — using first reachable server: %s",
        candidates[0]["base_url"],
    )
    return candidates[0]["base_url"]
