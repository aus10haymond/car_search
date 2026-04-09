"""
Builds Carvana search URLs.

Carvana encodes filters as JSON → base64 in the `cvnaid` query parameter.
"""

import base64
import json


def build_search_url(
    make: str,
    model: str,
    min_year: int,
    max_year: int,
    page: int = 1,
    fuel_type: str | None = None,
) -> str:
    """
    Returns a Carvana search URL with base64-encoded filter params.

    Example output:
      https://www.carvana.com/cars/filters?cvnaid=<base64>&page=2

    Filter JSON shape (matches Carvana's own URL format):
    {
      "filters": {
        "fuelTypes": ["Hybrid"],          # optional
        "makes": [{"name": "Toyota", "parentModels": [{"name": "RAV4"}]}],
        "year": {"min": 2021, "max": 2025}
      }
    }
    """
    inner: dict = {
        "makes": [{"name": make, "parentModels": [{"name": model}]}],
        "year": {"min": min_year, "max": max_year},
    }
    if fuel_type:
        inner["fuelTypes"] = [fuel_type]

    filters = {"filters": inner}
    encoded = base64.b64encode(
        json.dumps(filters, separators=(",", ":")).encode()
    ).decode()

    url = f"https://www.carvana.com/cars/filters?cvnaid={encoded}"
    if page > 1:
        url += f"&page={page}"
    return url
