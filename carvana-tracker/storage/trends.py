"""
Price trend chart generation using QuickChart.io.

Generates image URLs that embed directly in email HTML as <img> tags.
No API key or extra dependency required — QuickChart is a free service.
"""

import json
import logging
import urllib.parse

log = logging.getLogger(__name__)

# Colours per vehicle model (consistent across runs)
_MODEL_COLOURS = {
    "Honda CR-V":      "#e74c3c",   # red
    "Toyota RAV4":     "#2980b9",   # blue
    "Subaru Forester": "#27ae60",   # green
    "Kia Sportage":    "#f39c12",   # orange
}
_FALLBACK_COLOURS = ["#8e44ad", "#16a085", "#d35400", "#2c3e50"]

_QUICKCHART_BASE = "https://quickchart.io/chart"


def build_trend_charts_html(trends: dict[str, list[dict]]) -> str:
    """
    Build HTML containing two chart images:
      1. Average price per model over time
      2. Minimum price per model over time (best deal available)

    Returns empty string if fewer than 2 data points exist for any model,
    or if trends is empty.
    """
    if not trends:
        return ""

    # Need at least 2 runs for a meaningful line
    has_trend = any(len(points) >= 2 for points in trends.values())

    avg_url = _build_chart_url(trends, metric="avg", title="Average Price by Model")
    min_url = _build_chart_url(trends, metric="min", title="Best Available Price by Model")

    if not avg_url:
        return ""

    note = "" if has_trend else (
        "<p style='color:#888;font-size:12px'>"
        "<em>Trend lines require at least 2 runs — more data will appear over time.</em>"
        "</p>"
    )

    return (
        "<h3>Price Trends</h3>"
        + note
        + "<h4 style='margin-bottom:4px'>Average Price by Model</h4>"
        + f"<p><img src='{avg_url}' alt='Average price trend' style='max-width:100%;border:1px solid #ddd;border-radius:4px'></p>"
        + "<h4 style='margin-bottom:4px'>Best Available Price by Model</h4>"
        + f"<p><img src='{min_url}' alt='Minimum price trend' style='max-width:100%;border:1px solid #ddd;border-radius:4px'></p>"
    )


def _build_chart_url(
    trends: dict[str, list[dict]],
    metric: str,
    title: str,
) -> str:
    """Build a QuickChart URL for a line chart of the given metric."""
    # Collect all unique date labels in order
    all_dates: list[str] = []
    seen: set[str] = set()
    for points in trends.values():
        for p in points:
            if p["date"] not in seen:
                all_dates.append(p["date"])
                seen.add(p["date"])

    if not all_dates:
        return ""

    datasets = []
    fallback_idx = 0
    for label, points in sorted(trends.items()):
        colour = _MODEL_COLOURS.get(label)
        if not colour:
            colour = _FALLBACK_COLOURS[fallback_idx % len(_FALLBACK_COLOURS)]
            fallback_idx += 1

        # Align data to date labels (None for missing dates)
        by_date = {p["date"]: p[metric] for p in points}
        data    = [by_date.get(d) for d in all_dates]

        datasets.append({
            "label":                label,
            "data":                 data,
            "borderColor":          colour,
            "backgroundColor":      colour + "22",  # 13% opacity fill
            "borderWidth":          2,
            "pointRadius":          4,
            "tension":              0.3,
            "spanGaps":             True,
        })

    chart_config = {
        "type": "line",
        "data": {
            "labels":   all_dates,
            "datasets": datasets,
        },
        "options": {
            "plugins": {
                "title": {
                    "display": True,
                    "text":    title,
                    "font":    {"size": 14},
                },
                "legend": {"position": "bottom"},
            },
            "scales": {
                "y": {
                    "ticks": {
                        "callback": "function(v){return '$'+v.toLocaleString()}",
                    },
                    "title": {"display": True, "text": "Price (USD)"},
                },
                "x": {
                    "title": {"display": True, "text": "Run Date"},
                },
            },
        },
    }

    encoded = urllib.parse.quote(json.dumps(chart_config, separators=(",", ":")))
    url     = f"{_QUICKCHART_BASE}?c={encoded}&w=600&h=300&bkg=white"
    log.debug("QuickChart URL length: %d chars", len(url))
    return url
