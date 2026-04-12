"""
Email notifications via Mailjet REST API.

Only sends when SEND_EMAIL = True in config.
Uses requests (already in requirements) — no additional SDK needed.
"""

import base64
import logging
import re
from datetime import datetime
from pathlib import Path

import requests

import config
from analysis.llm import LLMResult
from storage.trends import build_trend_charts_html

log = logging.getLogger(__name__)

_MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"
_VERSION = "0.6.0"


def should_send(
    listings: list[dict],
    new_vins: set[str],
    price_drops: list[dict],
    max_price: int = 0,
) -> bool:
    """
    Return True if any alert condition is met:
    - max_price is None (no budget cap) and there are any listings → always send
    - Any listing below max_price (the profile's budget)
    - Any new listing with value_score > 70
    - Any listing with a price drop >= 5%
    """
    if max_price is None and listings:
        return True
    if max_price is not None and max_price > 0 and any((r.get("price") or 999999) < max_price for r in listings):
        return True
    if any(r.get("vin") in new_vins and (r.get("value_score") or 0) > 70 for r in listings):
        return True
    if price_drops:
        return True
    return False


def send_summary(
    listings: list[dict],
    llm_result: LLMResult,
    price_drops: list[dict],
    trends: dict | None = None,
    csv_path: Path | str | None = None,
    force: bool = False,
    new_vins: set[str] | None = None,
    email_to: list[str] | None = None,
    profile_label: str = "Carvana Tracker",
) -> bool:
    """
    Send an HTML email summary via Mailjet with the CSV attached.

    Returns True on success, False on failure or if conditions not met.
    Only sends when SEND_EMAIL=True (or force=True).
    email_to specifies the recipients for this profile's email.
    """
    if not config.SEND_EMAIL and not force:
        log.debug("Email skipped (SEND_EMAIL=False)")
        return False

    if not _is_configured():
        log.warning("Email not sent — Mailjet credentials or recipients not configured")
        return False

    recipients_list = email_to or []
    if not recipients_list:
        log.warning("Email not sent — no recipients configured")
        return False

    subject = _build_subject(listings, price_drops, profile_label)
    html    = _build_html(listings, llm_result, price_drops, trends or {}, new_vins or set(),
                          profile_label)

    recipients = [{"Email": addr} for addr in recipients_list]

    message: dict = {
        "From":     {"Email": config.EMAIL_FROM, "Name": config.EMAIL_FROM_NAME},
        "To":       recipients,
        "Subject":  subject,
        "HTMLPart": html,
    }

    if csv_path and Path(csv_path).exists():
        try:
            with open(csv_path, "rb") as f:
                csv_b64 = base64.b64encode(f.read()).decode()
            message["Attachments"] = [{
                "ContentType":  "text/csv",
                "Filename":     Path(csv_path).name,
                "Base64Content": csv_b64,
            }]
            log.debug("CSV attached: %s", Path(csv_path).name)
        except Exception as exc:
            log.warning("Could not attach CSV: %s", exc)

    payload = {"Messages": [message]}

    resp = None
    try:
        resp = requests.post(
            _MAILJET_SEND_URL,
            auth=(config.MAILJET_API_KEY, config.MAILJET_SECRET_KEY),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Email sent to %d recipient(s) via Mailjet", len(recipients))
        return True
    except requests.HTTPError as exc:
        body = resp.text[:300] if resp is not None else ""
        log.error("Mailjet HTTP error: %s — %s", exc, body)
    except Exception as exc:
        log.error("Email send failed: %s", exc)
    return False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_configured() -> bool:
    return bool(
        config.MAILJET_API_KEY
        and config.MAILJET_SECRET_KEY
        and config.EMAIL_FROM
    )


def _build_subject(
    listings: list[dict],
    price_drops: list[dict],
    profile_label: str = "Carvana Tracker",
) -> str:
    n    = len(listings)
    top  = listings[0] if listings else None
    drops = len(price_drops)
    if top:
        top_label = (
            f"{top.get('year')} {top.get('make')} {top.get('model')} "
            f"— ${top.get('price', 0):,.0f}"
        )
        drop_str = f" | {drops} price drop{'s' if drops != 1 else ''}" if drops else ""
        return f"{profile_label} | {top_label}{drop_str} | {n} listings"
    return f"{profile_label} — {n} listings"


def _build_html(
    listings: list[dict],
    llm_result: LLMResult,
    price_drops: list[dict],
    trends: dict,
    new_vins: set[str] | None = None,
    profile_label: str = "Carvana Tracker",
) -> str:
    run_time = datetime.now().strftime("%b %d, %Y %I:%M %p")
    top10    = listings[:10]

    # Top 3 by value_score within top10 — marked as AI top picks
    top3_vins: set[str] = {
        r["vin"]
        for r in sorted(top10, key=lambda x: -(x.get("value_score") or 0))[:3]
        if r.get("vin")
    }
    drop_by_vin: dict[str, dict] = {d["vin"]: d for d in price_drops if d.get("vin")}
    new_vins = new_vins or set()

    parts = [
        "<html><body style='font-family:sans-serif;max-width:880px;margin:auto;color:#222;line-height:1.5'>",
        f"<h2 style='margin-bottom:4px'>{profile_label} — {run_time}</h2>",
        f"<p style='color:#555;margin-top:0'>Found <b>{len(listings)}</b> listings matching your filters.</p>",
    ]

    # ── Top 10 table ──────────────────────────────────────────────────────────
    parts.append("<h3 style='margin-bottom:4px'>Top 10 Listings</h3>")
    parts.append(
        "<p style='font-size:12px;color:#666;margin-top:0'>"
        "<b>★</b> = AI top pick by value score &nbsp;|&nbsp;"
        "<span style='background:#fffde7;padding:1px 5px;border:1px solid #f0e68c'>&nbsp;</span>"
        " = price drop since last run &nbsp;|&nbsp;"
        "<span style='background:#27ae60;color:white;font-size:11px;padding:1px 5px;"
        "border-radius:3px'>NEW</span> = first time seen"
        "</p>"
    )
    parts.append(
        "<table border='1' cellpadding='7' cellspacing='0' "
        "style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr style='background:#f0f0f0;text-align:left'>"
        "<th>#</th><th>Vehicle</th><th>Color</th><th>Trim</th><th>Price</th>"
        "<th>Mileage</th><th>Est. Payment</th><th>Score</th><th>Hybrid</th><th></th>"
        "</tr>"
    )

    for i, r in enumerate(top10, start=1):
        vin      = r.get("vin") or ""
        url      = r.get("url") or "#"
        price    = r.get("price") or 0
        mileage  = r.get("mileage")
        is_drop  = vin in drop_by_vin
        is_pick  = vin in top3_vins
        is_new   = vin in new_vins

        row_bg   = "background:#fffde7" if is_drop else ""
        position = f"<b>★ {i}</b>" if is_pick else str(i)

        if is_drop:
            drop_pct   = drop_by_vin[vin].get("drop_pct", "")
            price_cell = (
                f"<b>${price:,.0f}</b>"
                f"<br><span style='color:#27ae60;font-size:11px'>▼ {drop_pct}% drop</span>"
            )
        else:
            price_cell = f"${price:,.0f}"

        hybrid_cell  = "<b style='color:#27ae60'>Yes</b>" if r.get("is_hybrid") else ""
        view_btn     = (
            f"<a href='{url}' style='background:#2980b9;color:white;padding:4px 10px;"
            f"border-radius:3px;text-decoration:none;font-size:12px;white-space:nowrap'>View</a>"
        )

        color_cell = (r.get("color_exterior") or "").strip()

        parts.append(
            f"<tr style='{row_bg}'>"
            f"<td style='text-align:center;white-space:nowrap'>{position}</td>"
            f"<td><b>{r.get('year')} {r.get('make')} {r.get('model')}</b>"
            + (" <span style='background:#27ae60;color:white;font-size:10px;padding:1px 4px;"
               "border-radius:3px;vertical-align:middle'>NEW</span>" if is_new else "")
            + "</td>"
            f"<td style='color:#555'>{color_cell}</td>"
            f"<td style='color:#555'>{(r.get('trim') or '')[:28]}</td>"
            f"<td>{price_cell}</td>"
            f"<td>{f'{mileage:,}' if mileage else 'N/A'}</td>"
            f"<td>${r.get('monthly_carvana') or r.get('monthly_estimated') or 0:,.0f}/mo</td>"
            f"<td style='text-align:center'>{int(r.get('value_score') or 0)}</td>"
            f"<td style='text-align:center'>{hybrid_cell}</td>"
            f"<td style='text-align:center'>{view_btn}</td>"
            f"</tr>"
        )

    parts.append("</table>")
    if any(r.get("vin") in drop_by_vin for r in top10):
        parts.append(
            "<p style='font-size:12px;color:#555;margin-top:4px'>"
            "Price drops are relative to the previous tracker run.</p>"
        )

    # ── LLM analysis ─────────────────────────────────────────────────────────
    if llm_result.analysis:
        backend_label = llm_result.backend_used.replace("_", " ").title()
        model_label   = f" ({llm_result.model_used})" if llm_result.model_used else ""
        parts.append(
            f"<h3 style='margin-top:28px'>AI Analysis "
            f"<small style='color:#666;font-weight:normal'>via {backend_label}{model_label}</small></h3>"
        )
        parts.append(
            "<div style='background:#f8f8f8;padding:14px 18px;border-radius:6px;"
            "font-size:13px;line-height:1.7;border:1px solid #e8e8e8'>"
            + _md_to_html(llm_result.analysis)
            + "</div>"
        )
    else:
        parts.append("<p><em>No AI analysis available this run.</em></p>")

    # ── Price trend charts ────────────────────────────────────────────────────
    trend_html = build_trend_charts_html(trends)
    if trend_html:
        parts.append("<div style='margin-top:28px'>" + trend_html + "</div>")

    # ── Footer ────────────────────────────────────────────────────────────────
    cache_str = ""
    if llm_result.cache_hit is True:
        cache_str = " | prompt cache: hit"
    elif llm_result.cache_hit is False:
        cache_str = " | prompt cache: miss"

    parts.append(
        f"<hr style='margin-top:32px'>"
        f"<p style='color:#999;font-size:12px'>"
        f"Carvana Tracker v{_VERSION} | "
        f"LLM: {llm_result.backend_used} ({llm_result.model_used or 'N/A'})"
        f"{cache_str} | "
        f"Full listing CSV attached"
        f"</p>"
        "</body></html>"
    )

    return "\n".join(parts)


# ── Markdown → HTML ───────────────────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """
    Convert the LLM's markdown output to clean inline HTML.
    Handles: headers, bold/italic, bullet lists, numbered lists, hr, paragraphs.
    No external dependencies.
    """
    lines   = text.split("\n")
    out     = []
    in_ul   = False
    in_ol   = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for line in lines:
        s = line.strip()

        # Unordered list item
        if re.match(r"^[-*] ", s):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul style='margin:6px 0;padding-left:22px'>")
                in_ul = True
            out.append(f"<li>{_inline_md(s[2:])}</li>")
            continue

        # Ordered list item
        if re.match(r"^\d+\.\s", s):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol style='margin:6px 0;padding-left:22px'>")
                in_ol = True
            content = re.sub(r"^\d+\.\s*", "", s)
            out.append(f"<li>{_inline_md(content)}</li>")
            continue

        close_lists()

        if not s:
            # Blank line — small vertical gap
            out.append("<div style='height:6px'></div>")
        elif s.startswith("### "):
            out.append(f"<h5 style='margin:10px 0 2px'>{_inline_md(s[4:])}</h5>")
        elif s.startswith("## "):
            out.append(f"<h4 style='margin:12px 0 4px'>{_inline_md(s[3:])}</h4>")
        elif s.startswith("# "):
            out.append(f"<h4 style='margin:12px 0 4px'>{_inline_md(s[2:])}</h4>")
        elif s in ("---", "***", "___"):
            out.append("<hr style='border:none;border-top:1px solid #ddd;margin:10px 0'>")
        else:
            out.append(f"<p style='margin:4px 0'>{_inline_md(s)}</p>")

    close_lists()
    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Convert inline markdown (bold, italic, code) to HTML."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic (single asterisk or underscore, not touching word boundaries aggressively)
    text = re.sub(r"\*([^*]+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+?)_",   r"<em>\1</em>", text)
    # Inline code
    text = re.sub(r"`(.+?)`", r"<code style='background:#eee;padding:1px 4px;border-radius:3px'>\1</code>", text)
    return text
