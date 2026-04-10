"""
Anthropic API client — fallback LLM backend.
"""

import logging

log = logging.getLogger(__name__)


class AnthropicUnavailableError(Exception):
    """Raised when the Anthropic API call fails."""


class AnthropicClient:
    def __init__(self, api_key: str, model: str, max_tokens: int):
        self.api_key    = api_key
        self.model      = model
        self.max_tokens = max_tokens

    def is_configured(self) -> bool:
        """Returns True if api_key is non-empty."""
        return bool(self.api_key)

    def analyze(self, prompt: str, reference_doc: str = "") -> tuple[str, bool | None]:
        """
        Calls anthropic.messages.create() with the user prompt.

        If reference_doc is non-empty it is passed as the first system block with
        cache_control: {"type": "ephemeral"} so Anthropic prompt caching applies.
        The analyst system context is passed as a second plain-text system block.

        Returns (response_text, cache_hit) where cache_hit is True when the
        reference doc tokens were served from cache, False when they were freshly
        computed, and None when no reference doc was provided.
        Raises AnthropicUnavailableError on API errors.
        Logs token usage at DEBUG level after each call.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise AnthropicUnavailableError(
                "anthropic package not installed — run: pip install anthropic"
            ) from exc
        assert anthropic is not None

        # Split the prompt at [SYSTEM CONTEXT] / [LISTINGS DATA] boundary so the
        # analyst persona lives in the system parameter alongside the reference doc.
        system_context_marker = "[SYSTEM CONTEXT]\n"
        listings_marker       = "\n\n[LISTINGS DATA]"
        if system_context_marker in prompt and listings_marker in prompt:
            sc_start = prompt.index(system_context_marker) + len(system_context_marker)
            sc_end   = prompt.index(listings_marker)
            analyst_context = prompt[sc_start:sc_end].strip()
            user_content    = prompt[sc_end + 2:].strip()  # strip leading \n\n
        else:
            analyst_context = ""
            user_content    = prompt

        system_blocks: list[dict] = []
        cache_hit: bool | None = None

        if reference_doc:
            system_blocks.append({
                "type": "text",
                "text": reference_doc,
                "cache_control": {"type": "ephemeral"},
            })
            cache_hit = False  # will be updated from usage below

        if analyst_context:
            system_blocks.append({"type": "text", "text": analyst_context})

        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            kwargs: dict = {
                "model":      self.model,
                "max_tokens": self.max_tokens,
                "messages":   [{"role": "user", "content": user_content}],
            }
            if system_blocks:
                kwargs["system"] = system_blocks
            message = client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            raise AnthropicUnavailableError(f"Anthropic API error: {exc}") from exc
        except Exception as exc:
            raise AnthropicUnavailableError(f"Unexpected error calling Anthropic API: {exc}") from exc

        usage = message.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        if reference_doc:
            cache_hit = cache_read > 0
        log.debug(
            "Anthropic token usage — input: %d, output: %d, cache_read: %d, cache_hit: %s",
            usage.input_tokens, usage.output_tokens, cache_read, cache_hit,
        )

        if not message.content:
            raise AnthropicUnavailableError("Anthropic API returned empty content")

        return message.content[0].text, cache_hit
