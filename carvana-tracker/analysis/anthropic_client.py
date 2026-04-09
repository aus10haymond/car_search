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

    def analyze(self, prompt: str) -> str:
        """
        Calls anthropic.messages.create() with the user prompt.
        Returns the text content of the first message block.
        Raises AnthropicUnavailableError on API errors.
        Logs token usage at DEBUG level after each call.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise AnthropicUnavailableError(
                "anthropic package not installed — run: pip install anthropic"
            ) from exc

        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            message = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            raise AnthropicUnavailableError(f"Anthropic API error: {exc}") from exc
        except Exception as exc:
            raise AnthropicUnavailableError(f"Unexpected error calling Anthropic API: {exc}") from exc

        usage = message.usage
        log.debug(
            "Anthropic token usage — input: %d, output: %d",
            usage.input_tokens, usage.output_tokens,
        )

        if not message.content:
            raise AnthropicUnavailableError("Anthropic API returned empty content")

        return message.content[0].text
