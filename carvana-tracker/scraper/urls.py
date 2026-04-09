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
) -> str:
    """
    Returns a Carvana search URL with base64-encoded filter params.

    Example output:
      https://www.carvana.com/cars/filters?cvnaid=<base64>&page=2

    Filter JSON shape:
    {
      "filters": {
        "makes": [{"name": "Toyota", "models": [{"name": "RAV4"}]}],
        "year": {"min": 2021, "max": 2025}
      }
    }
    """
    filters = {
        "filters": {
            "makes": [{"name": make, "models": [{"name": model}]}],
            "year": {"min": min_year, "max": max_year},
        }
    }
    encoded = base64.b64encode(
        json.dumps(filters, separators=(",", ":")).encode()
    ).decode()

    url = f"https://www.carvana.com/cars/filters?cvnaid={encoded}"
    if page > 1:
        url += f"&page={page}"
    return url
