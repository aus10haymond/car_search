"""
Shared vehicle reference doc generation.
Tries NVIDIA NIM first, falls back to Cerebras.
Used by both the desktop (/docs/generate) and portal (/portal/docs/generate) routers.
"""

import config

_NVIDIA_BASE_URL   = "https://integrate.api.nvidia.com/v1"
_CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"


def _build_prompt(make: str, model_name: str, year_start: int, year_end: int, notes: str) -> str:
    years = f"{year_start}–{year_end}"
    notes_line = f"\nAdditional buyer context: {notes.strip()}" if notes.strip() else ""
    return f"""Generate a comprehensive vehicle reference guide for the {years} {make} {model_name} in Markdown format.

This document will be fed to an AI system to help evaluate used car listings on Carvana. Be specific, accurate, and practical.

Structure the document exactly as shown:

# {make} {model_name} Reference Guide — Carvana Listing Evaluation Context

## Part 1 — Model Overview & Reliability
Covered generation(s), reliability summary, engine options, MPG (city/highway), cargo space, towing capacity.

## Part 2 — Trim Level Reference
Markdown table with columns: Trim | Years | Type (Gas/Hybrid/PHEV) | MPG (AWD) | Key Features | Notes

## Part 3 — Pricing Context
Expected used pricing by year and trim for {years}. Note significant value cliffs between years.

## Part 4 — Common Issues & Recalls
Known reliability problems, TSBs, and recalls for this generation. Be specific about which years/mileage are affected.

## Part 5 — Evaluation Tips
How to identify trims from a Carvana listing description, what to look for, red flags to avoid.{notes_line}

Focus only on the {years} generation. Include hybrid/PHEV variants if they exist for this vehicle."""


def generate_vehicle_doc(make: str, model_name: str, year_start: int, year_end: int, notes: str = "") -> str:
    """
    Generate a vehicle reference markdown doc. Tries NVIDIA NIM first, Cerebras as fallback.
    Returns the content string.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed — run: pip install openai")

    prompt = _build_prompt(make, model_name, year_start, year_end, notes)

    # ── Primary: NVIDIA NIM ───────────────────────────────────────────────────
    if config.NVIDIA_API_KEY:
        try:
            client = OpenAI(api_key=config.NVIDIA_API_KEY, base_url=_NVIDIA_BASE_URL)
            response = client.chat.completions.create(
                model=config.NVIDIA_MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "NVIDIA NIM doc generation failed: %s — falling back to Cerebras", exc
            )

    # ── Fallback: Cerebras ────────────────────────────────────────────────────
    if not config.CEREBRAS_API_KEY:
        raise ValueError(
            "NVIDIA_API_KEY and CEREBRAS_API_KEY are both unconfigured — add at least one to .env"
        )
    client = OpenAI(api_key=config.CEREBRAS_API_KEY, base_url=_CEREBRAS_BASE_URL)
    response = client.chat.completions.create(
        model=config.CEREBRAS_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
