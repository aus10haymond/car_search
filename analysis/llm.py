"""
LLM analysis orchestrator — network Ollama primary, Anthropic API fallback.

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
        show_financing: bool = True,
        down_payment: int | None = None,
    ):
        self.ollama = OllamaClient(
            base_url=config.OLLAMA_NETWORK_BASE_URL,
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
        self._show_financing  = show_financing
        self._down_payment    = down_payment if down_payment is not None else config.DOWN_PAYMENT

    def analyze(
        self,
        listings: list[dict],
        reference_doc: str | None = None,
        _prompt_override: str | None = None,
    ) -> LLMResult:
        """
        1. If OLLAMA_ENABLED and network Ollama has a model loaded:
               try ollama.analyze(prompt, model=loaded_model)
               on success: return result with backend_used="ollama"
               on OllamaUnavailableError or OllamaModelError:
                   log WARNING, fall through to step 2

        2. If ANTHROPIC_ENABLED and anthropic.is_configured():
               try anthropic.analyze(prompt)
               on success: return result with backend_used="anthropic_api"
               on AnthropicUnavailableError:
                   log ERROR, fall through to step 3

        3. Neither backend available:
               return LLMResult with backend_used="none", analysis=None

        Never raises. Always returns an LLMResult.

        reference_doc: optional override for this call only; falls back to
        the doc set at __init__ time if not provided.
        """
        effective_ref = reference_doc if reference_doc is not None else self._reference_doc
        if _prompt_override is not None:
            prompt = _prompt_override
            # _last_id_to_vin must already be set by the caller (e.g. build_synthesis_prompt)
        else:
            prompt = self.build_prompt(listings)

        # ── Step 1: Network Ollama (primary) ──────────────────────────────────
        if config.OLLAMA_ENABLED and config.OLLAMA_NETWORK_BASE_URL:
            loaded_model = self.ollama.get_loaded_model()
            if not loaded_model:
                loaded_model = self.ollama.get_preferred_model(config.OLLAMA_PREFERRED_MODELS)
                if loaded_model:
                    log.info(
                        "Network Ollama: no model loaded — will load preferred model %s",
                        loaded_model,
                    )
                else:
                    log.warning(
                        "Network Ollama: no model loaded and no preferred model installed "
                        "— falling back to Anthropic API"
                    )

            if loaded_model:
                t0 = time.monotonic()
                try:
                    ollama_ref = effective_ref
                    max_chars  = config.OLLAMA_REF_DOC_MAX_CHARS
                    if max_chars and ollama_ref and len(ollama_ref) > max_chars:
                        log.warning(
                            "Reference doc truncated from %d to %d chars for Ollama "
                            "(full doc is still sent to Anthropic API)",
                            len(ollama_ref), max_chars,
                        )
                        ollama_ref = ollama_ref[:max_chars]
                    text = self.ollama.analyze(
                        prompt, reference_doc=ollama_ref, model=loaded_model
                    )
                    latency = int((time.monotonic() - t0) * 1000)
                    log.info(
                        "LLM analysis complete via network Ollama/%s (%dms)",
                        loaded_model, latency,
                    )
                    self.backend_used = "ollama"
                    cleaned_text, top_pick_vins = self._parse_top_picks(text)
                    return LLMResult(
                        analysis=cleaned_text,
                        backend_used="ollama",
                        model_used=loaded_model,
                        tokens_used=None,
                        latency_ms=latency,
                        error=None,
                        top_pick_vins=top_pick_vins,
                    )
                except (OllamaUnavailableError, OllamaModelError) as exc:
                    log.warning(
                        "Network Ollama failed: %s — falling back to Anthropic API", exc
                    )
        elif config.OLLAMA_ENABLED:
            log.debug("OLLAMA_NETWORK_HOST not set — skipping Ollama")
        else:
            log.debug("Ollama disabled in config")

        # ── Step 2: Anthropic API (fallback) ──────────────────────────────────
        if config.ANTHROPIC_ENABLED:
            if self.anthropic.is_configured():
                t0 = time.monotonic()
                try:
                    text, cache_hit = self.anthropic.analyze(
                        prompt, reference_doc=effective_ref
                    )
                    latency = int((time.monotonic() - t0) * 1000)
                    log.info(
                        "LLM analysis complete via Anthropic API (%dms, cache_hit=%s)",
                        latency, cache_hit,
                    )
                    self.backend_used = "anthropic_api"
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
                    log.error(
                        "Anthropic API failed: %s — no LLM analysis available", exc
                    )
            else:
                log.warning("Anthropic API key not configured — no LLM analysis available")
        else:
            log.debug("Anthropic API disabled in config")

        # ── Step 3: No backend available ──────────────────────────────────────
        self.backend_used = "none"
        return LLMResult(
            analysis=None,
            backend_used="none",
            model_used="",
            tokens_used=None,
            latency_ms=0,
            error="No LLM backend available (network Ollama unreachable/no model loaded, Anthropic API not configured or disabled)",
        )

    @staticmethod
    def _strip_id_refs(text: str) -> str:
        """
        Remove LLM-generated ID references from analysis prose.

        Handles patterns like:
          — ID 2          (dash + ID)
          (ID 1)          (parenthetical single)
          (IDs 7 and 8)   (parenthetical list)
          (IDs 19–23)     (parenthetical range)
          ID 2 wins.      (bare reference)
        """
        import re
        # "— ID N" or "– ID N" (with optional surrounding whitespace)
        text = re.sub(r'\s*[—–]\s*ID\s+\d+', '', text)
        # "(ID N)" or "(IDs N, M)" or "(IDs N–M)" or "(IDs N and M)"
        text = re.sub(r'\s*\(IDs?\s+[\d,\s–—and]+\)', '', text)
        # "ID N and ID M" compound references (before bare-ID pass to avoid orphaned "and")
        text = re.sub(r'\bID\s+\d+(\s*(?:and|,)\s*ID\s+\d+)+\b', '', text)
        # bare "ID N" remaining (word boundary)
        text = re.sub(r'\bID\s+\d+\b', '', text)
        # collapse any double-spaces left behind
        text = re.sub(r' {2,}', ' ', text)
        return text

    def _parse_top_picks(self, text: str) -> tuple[str, list[str]]:
        """
        Extract the TOP_PICKS line from the LLM response.

        Returns (cleaned_text, list_of_vins).
        The TOP_PICKS line is stripped from the returned text so it doesn't
        appear in the email's analysis section.  Any residual "ID N" references
        the LLM included in prose are also stripped.
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

        cleaned = self._strip_id_refs("\n".join(kept_lines).rstrip())
        if top_pick_vins:
            log.debug("LLM top picks (VINs): %s", top_pick_vins)
        else:
            log.warning("LLM did not return a parseable TOP_PICKS line")
        return cleaned, top_pick_vins

    def _build_listings_table(self, listings: list[dict]) -> str:
        """
        Build the markdown listings table and set self._last_id_to_vin.
        Caps at 30 rows. Returns the table string.
        Shared by build_prompt() and build_synthesis_prompt().
        """
        top_listings = listings[:min(30, len(listings))]
        self._last_id_to_vin: dict[int, str] = {}

        if self._show_financing:
            header = "| ID | Year | Make | Model | Trim | Price | Mileage | Est. Payment | Value Score | Hybrid |"
            sep    = "|----|------|------|-------|------|-------|---------|--------------|-------------|--------|"
        else:
            header = "| ID | Year | Make | Model | Trim | Price | Mileage | Value Score | Hybrid |"
            sep    = "|----|------|------|-------|------|-------|---------|-------------|--------|"

        rows: list[str] = []
        for idx, r in enumerate(top_listings, start=1):
            self._last_id_to_vin[idx] = r.get("vin") or ""
            trim    = "[HYBRID] " + (r.get("trim") or "") if r.get("is_hybrid") else (r.get("trim") or "")
            price   = f"${round(r.get('price') or 0):,}"
            mileage = f"{round((r.get('mileage') or 0) / 100) * 100:,}"
            score   = int(r.get("value_score") or 0)
            if self._show_financing:
                payment = f"${r.get('monthly_carvana') or r.get('monthly_estimated') or 0:,.0f}/mo"
                rows.append(
                    f"| {idx} | {r.get('year')} | {r.get('make')} | {r.get('model')} | {trim} "
                    f"| {price} | {mileage} | {payment} | {score} | {'Yes' if r.get('is_hybrid') else 'No'} |"
                )
            else:
                rows.append(
                    f"| {idx} | {r.get('year')} | {r.get('make')} | {r.get('model')} | {trim} "
                    f"| {price} | {mileage} | {score} | {'Yes' if r.get('is_hybrid') else 'No'} |"
                )

        return "\n".join([header, sep] + rows)

    def build_prompt(self, listings: list[dict]) -> str:
        """
        Build the per-make analysis prompt.
        Caps the listings table at 30 rows (top by value_score).
        """
        from datetime import datetime, timezone

        run_ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        total_shown = min(30, len(listings))
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
        financing_note = (
            f"They plan to finance with ${self._down_payment:,} down, "
            f"at {config.INTEREST_RATE}% APR over {config.LOAN_TERM_MONTHS} months.\n"
            if self._show_financing else ""
        )
        system_context = (
            f"You are an automotive analyst helping a buyer find the best used vehicle deal on Carvana.\n"
            f"The buyer is located in Phoenix, AZ. Their budget is {budget_str}.\n"
            f"{fuel_note} {financing_note}"
            f"Analyze the listings below and provide a clear, practical recommendation.\n"
            f"Do not speculate beyond the data provided. Flag any data that looks unusual."
            f"{no_ref_note}"
        )

        header = (
            f"Run: {run_ts} | "
            f"Total listings before filtering: (see prior log) | "
            f"Listings shown: {total_shown}"
        )

        table = self._build_listings_table(listings)  # also sets _last_id_to_vin

        # Top 5 highlight block
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
            "Keep the response under 600 words. Use plain language. Avoid filler phrases.\n"
            "In your written analysis, refer to listings by year, make, model, trim, and price "
            "(e.g. '2024 Toyota RAV4 XLE at $31,500') — do not use ID numbers.\n\n"
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

    def build_synthesis_prompt(
        self,
        all_listings: list[dict],
        per_make_analyses: list[tuple[str, str]],
    ) -> str:
        """
        Build a cross-model synthesis prompt after all per-make analyses are done.

        The returned prompt asks the LLM to compare across ALL makes and produce:
          - Top 3 best deals across all models
          - One final recommendation

        Calling this also sets self._last_id_to_vin against `all_listings` so
        that _parse_top_picks correctly maps IDs back to VINs.
        """
        budget_str = f"${self._max_price:,}" if self._max_price else "their stated budget"
        fuel_note  = (
            "particularly interested in hybrid trims"
            if self._has_hybrid
            else "open to all fuel types"
        )
        financing_note = (
            f"Financing: ${self._down_payment:,} down, "
            f"{config.INTEREST_RATE}% APR, {config.LOAN_TERM_MONTHS} months.\n"
            if self._show_financing else ""
        )

        system_context = (
            f"You are an automotive analyst. Multiple per-make analyses have been completed "
            f"for a buyer in Phoenix, AZ. Budget: {budget_str}. Buyer is {fuel_note}. "
            f"{financing_note}"
            f"Your task is to synthesize the per-make findings into a single cross-model recommendation."
        )

        # Truncate each per-make analysis to keep the prompt size reasonable
        summaries = "\n\n".join(
            f"### {make}\n{analysis[:1200]}{'…' if len(analysis) > 1200 else ''}"
            for make, analysis in per_make_analyses
        )

        # Full cross-model table — sets _last_id_to_vin as a side effect
        table = self._build_listings_table(all_listings)

        synthesis_request = (
            "Based on the per-make analyses above and the full listing table below, provide:\n\n"
            "1. **Top 3 best deals across ALL makes and models.** For each, state the vehicle "
            "(year, make, model, trim, price), why it beats cross-model alternatives, and the "
            "estimated monthly payment.\n"
            "2. **One final recommendation** — a single specific vehicle — with a concise rationale "
            "for why it is the best pick across the entire dataset.\n\n"
            "Keep this section under 350 words. Refer to vehicles by year, make, model, trim, and "
            "price — do not use ID numbers in the written text.\n\n"
            "At the very end, on its own line, write exactly:\n"
            "TOP_PICKS: <comma-separated IDs of your top 3 picks from the full listing table>\n"
            "Example: TOP_PICKS: 3,11,22\n"
            "Use the ID column from the full listing table. Do not add any text after this line."
        )

        return (
            f"[SYSTEM CONTEXT]\n{system_context}\n\n"
            f"[PER-MAKE ANALYSES]\n{summaries}\n\n"
            f"[FULL LISTING TABLE — ALL MAKES]\n{table}\n\n"
            f"[SYNTHESIS REQUEST]\n{synthesis_request}"
        )
