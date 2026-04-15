"""
LLM analysis orchestrator — Anthropic API primary, Ollama fallback.

This is the only module that imports both clients.
"""

import logging
import time
from dataclasses import dataclass, field

import config
from analysis.ollama_client import OllamaClient, OllamaUnavailableError, OllamaModelError
from analysis.anthropic_client import AnthropicClient, AnthropicUnavailableError

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    analysis:       str | None        # The LLM's text output, or None if unavailable
    backend_used:   str               # "ollama" | "anthropic_api" | "none"
    model_used:     str               # Specific model string e.g. "llama3.1:8b"
    tokens_used:    int | None        # None for Ollama (not always available)
    latency_ms:     int               # Wall-clock time for the LLM call
    error:          str | None        # Error message if backend failed, else None
    cache_hit:      bool | None = None  # True/False if Anthropic cache was checked; None otherwise
    top_pick_vins:  list[str] = field(default_factory=list)  # VINs the LLM identified as top picks


class LLMAnalyzer:
    def __init__(
        self,
        reference_doc: str = "",
        max_price: int = 0,
        has_hybrid_interest: bool = False,
    ):
        self.ollama = OllamaClient(
            base_url=config.OLLAMA_BASE_URL,
            model=config.OLLAMA_MODEL,
            timeout=config.OLLAMA_TIMEOUT,
        )
        self.anthropic = AnthropicClient(
            api_key=config.ANTHROPIC_API_KEY,
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.ANTHROPIC_MAX_TOKENS,
        )
        self.backend_used: str | None = None
        self._reference_doc   = reference_doc
        self._max_price       = max_price
        self._has_hybrid      = has_hybrid_interest

    def analyze(self, listings: list[dict]) -> LLMResult:
        """
        1. If ANTHROPIC_ENABLED and anthropic.is_configured():
               try anthropic.analyze(prompt)
               on success: return result with backend_used="anthropic_api"
               on AnthropicUnavailableError:
                   log WARNING, fall through to step 2

        2. If OLLAMA_ENABLED and ollama.is_available():
               try ollama.analyze(prompt)
               on success: return result with backend_used="ollama"
               on OllamaUnavailableError or OllamaModelError:
                   log ERROR, fall through to step 3

        3. Neither backend available:
               return LLMResult with backend_used="none", analysis=None

        Never raises. Always returns an LLMResult.
        """
        prompt = self.build_prompt(listings)

        # ── Step 1: Anthropic API (primary) ───────────────────────────────────
        if config.ANTHROPIC_ENABLED:
            if self.anthropic.is_configured():
                t0 = time.monotonic()
                try:
                    text, cache_hit = self.anthropic.analyze(prompt, reference_doc=self._reference_doc)
                    latency = int((time.monotonic() - t0) * 1000)
                    log.info(
                        "LLM analysis complete via Anthropic API (%dms, cache_hit=%s)",
                        latency, cache_hit,
                    )
                    self.backend_used = "anthropic_api"
                    if config.OLLAMA_ENABLED:
                        self.ollama.unload()
                    cleaned_text, top_pick_vins = self._parse_top_picks(text)
                    return LLMResult(
                        analysis=cleaned_text,
                        backend_used="anthropic_api",
                        model_used=config.ANTHROPIC_MODEL,
                        tokens_used=None,
                        latency_ms=latency,
                        error=None,
                        cache_hit=cache_hit,
                        top_pick_vins=top_pick_vins,
                    )
                except AnthropicUnavailableError as exc:
                    log.warning("Anthropic API failed: %s — falling back to Ollama", exc)
            else:
                log.warning("Anthropic API key not configured — falling back to Ollama")
        else:
            log.debug("Anthropic API disabled in config")

        # ── Step 2: Ollama (fallback) ─────────────────────────────────────────
        if config.OLLAMA_ENABLED:
            if self.ollama.is_available():
                t0 = time.monotonic()
                try:
                    text = self.ollama.analyze(prompt, reference_doc=self._reference_doc)
                    latency = int((time.monotonic() - t0) * 1000)
                    log.info("LLM analysis complete via Ollama (%dms)", latency)
                    self.backend_used = "ollama"
                    self.ollama.unload()
                    cleaned_text, top_pick_vins = self._parse_top_picks(text)
                    return LLMResult(
                        analysis=cleaned_text,
                        backend_used="ollama",
                        model_used=config.OLLAMA_MODEL,
                        tokens_used=None,
                        latency_ms=latency,
                        error=None,
                        top_pick_vins=top_pick_vins,
                    )
                except (OllamaUnavailableError, OllamaModelError) as exc:
                    log.error("Ollama failed: %s — no LLM analysis available", exc)
            else:
                log.warning("Ollama is not available (model=%s) — no LLM analysis available", config.OLLAMA_MODEL)
        else:
            log.debug("Ollama disabled in config")

        # ── Step 3: No backend available ──────────────────────────────────────
        self.backend_used = "none"
        return LLMResult(
            analysis=None,
            backend_used="none",
            model_used="",
            tokens_used=None,
            latency_ms=0,
            error="No LLM backend available (Ollama unavailable, Anthropic API not configured or disabled)",
        )

    def _parse_top_picks(self, text: str) -> tuple[str, list[str]]:
        """
        Extract the TOP_PICKS line from the LLM response.

        Returns (cleaned_text, list_of_vins).
        The TOP_PICKS line is stripped from the returned text so it doesn't
        appear in the email's analysis section.
        """
        id_to_vin = getattr(self, "_last_id_to_vin", {})
        lines = text.splitlines()
        top_pick_vins: list[str] = []
        kept_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.upper().startswith("TOP_PICKS:"):
                raw_ids = stripped[len("TOP_PICKS:"):].strip()
                for part in raw_ids.split(","):
                    try:
                        row_id = int(part.strip())
                        vin = id_to_vin.get(row_id, "")
                        if vin:
                            top_pick_vins.append(vin)
                    except ValueError:
                        pass
            else:
                kept_lines.append(line)

        cleaned = "\n".join(kept_lines).rstrip()
        if top_pick_vins:
            log.debug("LLM top picks (VINs): %s", top_pick_vins)
        else:
            log.warning("LLM did not return a parseable TOP_PICKS line")
        return cleaned, top_pick_vins

    def build_prompt(self, listings: list[dict]) -> str:
        """
        Build the analysis prompt per Section 5 of the architecture spec.
        Caps the listings table at 30 rows (top by value_score).
        """
        from datetime import datetime, timezone

        run_ts       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        # Use listings in the order they arrive (already sorted by model_preference
        # then value_score in main.py) so the table IDs map 1:1 to email row numbers.
        total_shown  = min(30, len(listings))
        top_listings = listings[:total_shown]

        fuel_note = (
            "They are particularly interested in hybrid trims."
            if self._has_hybrid
            else "They are open to all fuel types."
        )
        budget_str = f"${self._max_price:,}" if self._max_price else "their stated budget"
        no_ref_note = (
            "\nNo vehicle reference document is available for this search. "
            "Evaluate listings based solely on the listing data provided."
            if not self._reference_doc
            else ""
        )
        system_context = (
            f"You are an automotive analyst helping a buyer find the best used vehicle deal on Carvana.\n"
            f"The buyer is located in Phoenix, AZ. Their budget is {budget_str}.\n"
            f"{fuel_note} They plan to finance with ${config.DOWN_PAYMENT:,} down,\n"
            f"at {config.INTEREST_RATE}% APR over {config.LOAN_TERM_MONTHS} months.\n"
            f"Analyze the listings below and provide a clear, practical recommendation.\n"
            f"Do not speculate beyond the data provided. Flag any data that looks unusual."
            f"{no_ref_note}"
        )

        header = (
            f"Run: {run_ts} | "
            f"Total listings before filtering: (see prior log) | "
            f"Listings shown: {total_shown}"
        )

        # Build markdown table — keep a mapping from row ID to VIN for top-pick parsing
        self._last_id_to_vin: dict[int, str] = {}
        table_header = "| ID | Year | Make | Model | Trim | Price | Mileage | Est. Payment | Value Score | Hybrid |"
        table_sep    = "|----|------|------|-------|------|-------|---------|--------------|-------------|--------|"
        table_rows   = []
        for idx, r in enumerate(top_listings, start=1):
            self._last_id_to_vin[idx] = r.get("vin") or ""
            trim    = (r.get("trim") or "")
            if r.get("is_hybrid"):
                trim = f"[HYBRID] {trim}"
            price   = f"${round(r.get('price') or 0):,}"
            mileage = f"{round((r.get('mileage') or 0) / 100) * 100:,}"
            payment = f"${r.get('monthly_carvana') or r.get('monthly_estimated') or 0:,.0f}/mo"
            score   = int(r.get("value_score") or 0)
            table_rows.append(
                f"| {idx} | {r.get('year')} | {r.get('make')} | {r.get('model')} | {trim} "
                f"| {price} | {mileage} | {payment} | {score} | {'Yes' if r.get('is_hybrid') else 'No'} |"
            )

        table = "\n".join([table_header, table_sep] + table_rows)

        # Top 5 highlight block (same order as table — IDs 1–5)
        top5 = top_listings[:5]
        top5_lines = "\n".join(
            f"ID {i+1}. {r.get('year')} {r.get('make')} {r.get('model')} {r.get('trim','')} "
            f"— ${r.get('price',0):,.0f}, {r.get('mileage') or 'N/A'} mi, score={int(r.get('value_score') or 0)}"
            for i, r in enumerate(top5)
        )

        analysis_request = (
            "1. Identify the top 3 overall best deals, explaining your reasoning for each.\n"
            "2. Identify the top hybrid deal specifically.\n"
            "3. Flag any listings that appear to be unusual (suspiciously low price, very high mileage for year, etc.).\n"
            "4. Note any patterns across the full dataset (e.g., 'RAV4 Hybrids are commanding a $3,000 premium over gas models in this dataset').\n"
            "5. Give one clear final recommendation with a brief rationale.\n\n"
            "Keep the response under 600 words. Use plain language. Avoid filler phrases.\n\n"
            "At the very end of your response, on its own line, write exactly:\n"
            "TOP_PICKS: <comma-separated IDs of your top 3 recommended listings>\n"
            "Example: TOP_PICKS: 2,5,11\n"
            "Use the ID column from the table above. Do not add any text after this line."
        )

        return (
            f"[SYSTEM CONTEXT]\n{system_context}\n\n"
            f"[LISTINGS DATA]\n{header}\n\n"
            f"{table}\n\n"
            f"Top 5 by value score:\n{top5_lines}\n\n"
            f"[ANALYSIS REQUEST]\n{analysis_request}"
        )
