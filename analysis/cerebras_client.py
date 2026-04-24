"""
Cerebras API client — uses the OpenAI-compatible Cerebras endpoint.
"""

import logging

log = logging.getLogger(__name__)

_CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"


class CerebrasUnavailableError(Exception):
    """Raised when the Cerebras API call fails."""


class CerebrasClient:
    def __init__(self, api_key: str, model: str, max_tokens: int):
        self.api_key    = api_key
        self.model      = model
        self.max_tokens = max_tokens

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def analyze(self, prompt: str, reference_doc: str = "") -> str:
        """
        Call Cerebras via the OpenAI-compatible API.

        Splits [SYSTEM CONTEXT] from the prompt (same boundary as the Anthropic
        client) and sends it as the system message alongside the reference doc.

        Returns the response text.
        Raises CerebrasUnavailableError on API errors.
        """
        try:
            from openai import OpenAI, APIError
        except ImportError as exc:
            raise CerebrasUnavailableError(
                "openai package not installed — run: pip install openai"
            ) from exc

        system_context_marker = "[SYSTEM CONTEXT]\n"
        listings_marker       = "\n\n[LISTINGS DATA]"
        if system_context_marker in prompt and listings_marker in prompt:
            sc_start = prompt.index(system_context_marker) + len(system_context_marker)
            sc_end   = prompt.index(listings_marker)
            analyst_context = prompt[sc_start:sc_end].strip()
            user_content    = prompt[sc_end + 2:].strip()
        else:
            analyst_context = ""
            user_content    = prompt

        system_parts: list[str] = []
        if reference_doc:
            system_parts.append(reference_doc)
        if analyst_context:
            system_parts.append(analyst_context)
        system_text = "\n\n".join(system_parts) if system_parts else None

        messages: list[dict] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user_content})

        try:
            client = OpenAI(api_key=self.api_key, base_url=_CEREBRAS_BASE_URL)
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=messages,
            )
        except APIError as exc:
            raise CerebrasUnavailableError(f"Cerebras API error: {exc}") from exc
        except Exception as exc:
            raise CerebrasUnavailableError(f"Unexpected error calling Cerebras API: {exc}") from exc

        content = response.choices[0].message.content
        usage = response.usage
        if usage:
            log.debug(
                "Cerebras token usage — input: %d, output: %d",
                usage.prompt_tokens, usage.completion_tokens,
            )

        if not content:
            raise CerebrasUnavailableError("Cerebras API returned empty content")

        return content
