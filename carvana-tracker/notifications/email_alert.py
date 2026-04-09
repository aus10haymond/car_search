"""
Email notifications via Mailjet REST API.

Only sends when SEND_EMAIL = True in config.
Uses requests (already in requirements) — no additional SDK needed.
"""

import logging
from datetime import datetime

import requests

import config
from analysis.llm import LLMResult
from storage.trends import build_trend_charts_html

log = logging.getLogger(__name__)

_MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"
_VERSION = "0.5.0"


def should_send(
    listings: list[dict],
    new_vins: set[str],
    price_drops: list[dict],
) -> bool:
    """
    Return True if any alert condition is met:
    - Any listing below ALERT_PRICE_THRESHOLD
    - Any new listing with value_score > 70
    - Any listing with a price drop >= 5%
    """
    if any((r.get("price") or 999999) < config.ALERT_PRICE_THRESHOLD for r in listings):
        return True
    if any(v in new_vins for v in (r.get("vin") for r in listings) if (r.get("value_score") or 0) > 70):
        return True
    if price_drops:
        return True
    return False


def send_summary(
    listings: list[dict],
    llm_result: LLMResult,
    new_vins: set[str],
    price_drops: list[dict],
    trends: dict | None = None,
    force: bool = False,
) -> bool:
    """
    Send an HTML email summary via Mailjet.

    Returns True on success, False on failure or if conditions not met.
    Only sends when SEND_EMAIL=True (or force=True).
    """
    if not config.SEND_EMAIL and not force:
        log.debug("Email skipped (SEND_EMAIL=False)")
        return False

    if not _is_configured():
        log.warning("Email not sent — Mailjet credentials or recipients not configured")
        return False

    alerts = _collect_alerts(listings, new_vins, price_drops)
    subject = _build_subject(listings, alerts)
    html    = _build_html(listings, llm_result, alerts, price_drops, trends or {})

    recipients = [{"Email": addr} for addr in config.EMAIL_TO]

    payload = {
        "Messages": [
            {
                "From":     {"Email": config.EMAIL_FROM, "Name": config.EMAIL_FROM_NAME},
                "To":       recipients,
                "Subject":  subject,
                "HTMLPart": html,
            }
        ]
    }

    try:
        resp = requests.post(
            _MAILJET_SEND_URL,
            auth=(config.MAILJET_API_KEY, config.MAILJET_SECRET_KEY),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Email sent to %d recipient(s) via Mailjet", len(config.EMAIL_TO))
        return True
    except requests.HTTPError as exc:
        log.error("Mailjet HTTP error: %s — %s", exc, resp.text[:300])
    except Exception as exc:
        log.error("Email send failed: %s", exc)
    return False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_configured() -> bool:
    return bool(
        config.MAILJET_API_KEY
        and config.MAILJET_SECRET_KEY
        and config.EMAIL_FROM
        and config.EMAIL_TO
    )


def _collect_alerts(
    listings: list[dict],
    new_vins: set[str],
    price_drops: list[dict],
) -> list[dict]:
    """Gather all listings that triggered an alert condition."""
    alert_vins: set[str] = set()
    alerts = []

    for r in listings:
        vin   = r.get("vin") or ""
        price = r.get("price") or 999999
        score = r.get("value_score") or 0

        reasons = []
        if price < config.ALERT_PRICE_THRESHOLD:
            reasons.append(f"under ${config.ALERT_PRICE_THRESHOLD:,}")
        if vin in new_vins and score > 70:
            reasons.append(f"new listing, score {int(score)}")

        if reasons and vin not in alert_vins:
            alert_vins.add(vin)
            alerts.append({**r, "_alert_reasons": ", ".join(reasons)})

    for drop in price_drops:
        vin = drop.get("vin") or ""
        if vin not in alert_vins:
            alert_vins.add(vin)
            alerts.append({**drop, "_alert_reasons": f"price drop {drop.get('drop_pct')}%"})

    return alerts


def _build_subject(listings: list[dict], alerts: list[dict]) -> str:
    n = len(listings)
    m = len(alerts)
    return f"Carvana Tracker — {n} listings | {m} alerts"


def _build_html(
    listings: list[dict],
    llm_result: LLMResult,
    alerts: list[dict],
    price_drops: list[dict],
    trends: dict,
) -> str:
    run_time = datetime.now().strftime("%b %d, %Y %I:%M %p")
    top20    = listings[:20]

    parts = [
        "<html><body style='font-family:sans-serif;max-width:900px;margin:auto;color:#222'>",
        f"<h2>Carvana SUV Tracker — {run_time}</h2>",
        f"<p>Found <b>{len(listings)}</b> listings matching your filters.</p>",
    ]

    # Alert section
    if alerts:
        parts.append(f"<h3 style='color:#c0392b'>Alerts ({len(alerts)})</h3><ul>")
        for r in alerts:
            url     = r.get("url") or "#"
            reasons = r.get("_alert_reasons", "")
            parts.append(
                f"<li><b>{r.get('year')} {r.get('make')} {r.get('model')} {r.get('trim','')}</b>"
                f" — ${r.get('price',0):,.0f} | {r.get('mileage') or 'N/A'} mi"
                f" | <em>{reasons}</em>"
                f" | <a href='{url}'>View on Carvana</a></li>"
            )
        parts.append("</ul>")

    # Price drops
    if price_drops:
        parts.append("<h3>Price Drops</h3><ul>")
        for d in price_drops:
            url = d.get("url") or "#"
            parts.append(
                f"<li>{d.get('year')} {d.get('make')} {d.get('model')} {d.get('trim','')}"
                f" — ${d.get('prev_price',0):,.0f} &rarr; <b>${d.get('price',0):,.0f}</b>"
                f" ({d.get('drop_pct')}% drop)"
                f" | <a href='{url}'>View</a></li>"
            )
        parts.append("</ul>")

    # Results table
    parts.append("<h3>Top 20 Listings (CR-V &rsaquo; RAV4 &rsaquo; Forester &rsaquo; Sportage, then by Value Score)</h3>")
    parts.append(
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr style='background:#f0f0f0'>"
        "<th>Vehicle</th><th>Trim</th><th>Price</th><th>Mileage</th>"
        "<th>Est. Payment</th><th>Score</th><th>Hybrid</th><th>Link</th>"
        "</tr>"
    )
    for r in top20:
        hybrid_badge = "<b style='color:green'>Y</b>" if r.get("is_hybrid") else ""
        url = r.get("url") or "#"
        parts.append(
            f"<tr>"
            f"<td>{r.get('year')} {r.get('make')} {r.get('model')}</td>"
            f"<td>{(r.get('trim') or '')[:20]}</td>"
            f"<td>${r.get('price',0):,.0f}</td>"
            f"<td>{r.get('mileage') or 'N/A'}</td>"
            f"<td>${r.get('monthly_estimated',0):,.0f}/mo</td>"
            f"<td>{int(r.get('value_score') or 0)}</td>"
            f"<td>{hybrid_badge}</td>"
            f"<td><a href='{url}'>View</a></td>"
            f"</tr>"
        )
    parts.append("</table>")

    # Price trend charts
    trend_html = build_trend_charts_html(trends)
    if trend_html:
        parts.append(trend_html)

    # LLM analysis
    if llm_result.analysis:
        backend_label = llm_result.backend_used.replace("_", " ").title()
        model_label   = f" ({llm_result.model_used})" if llm_result.model_used else ""
        parts.append(
            f"<h3>AI Analysis <small style='color:#666;font-weight:normal'>"
            f"via {backend_label}{model_label}</small></h3>"
            f"<pre style='background:#f8f8f8;padding:12px;border-radius:4px;"
            f"white-space:pre-wrap;font-size:13px'>{llm_result.analysis}</pre>"
        )
    else:
        parts.append("<p><em>No AI analysis available this run.</em></p>")

    # Footer
    parts.append(
        f"<hr><p style='color:#888;font-size:12px'>"
        f"Carvana Tracker v{_VERSION} | "
        f"LLM backend: {llm_result.backend_used} | "
        f"<a href='https://github.com'>source</a></p>"
        "</body></html>"
    )

    return "\n".join(parts)
