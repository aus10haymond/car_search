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
      https://www.carvana.com/cars/filters?cvnaid=<base64>

    Payload JSON shape (page is encoded inside cvnaid, not as a query param):
    {
      "filters": {
        "fuelTypes": ["Hybrid"],          # optional
        "makes": [{"name": "Toyota", "parentModels": [{"name": "RAV4"}]}],
        "year": {"min": 2021, "max": 2025}
      },
      "page": 2                           # omitted for page 1
    }
    """
    inner: dict = {
        "makes": [{"name": make, "parentModels": [{"name": model}]}],
        "year": {"min": min_year, "max": max_year},
    }
    if fuel_type:
        inner["fuelTypes"] = [fuel_type]

    payload: dict = {"filters": inner}
    if page > 1:
        payload["page"] = page

    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()

    return f"https://www.carvana.com/cars/filters?cvnaid={encoded}"
