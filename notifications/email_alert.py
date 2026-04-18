"""
Email notifications via Gmail API (OAuth2).

Only sends when SEND_EMAIL = True in config.
Uses requests (already in requirements) at runtime — no extra packages needed.

One-time setup: run  python setup_gmail_oauth.py  to get your refresh token.
"""

import base64
import logging
import re
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

import requests

import config
from analysis.llm import LLMResult
from storage.trends import build_trend_charts_html

log = logging.getLogger(__name__)

_TOKEN_URL   = "https://oauth2.googleapis.com/token"
_SEND_URL    = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_VERSION     = "0.6.0"


# ── OAuth token refresh ───────────────────────────────────────────────────────

def _get_access_token() -> str | None:
    """Exchange the stored refresh token for a short-lived access token."""
    try:
        resp = requests.post(
            _TOKEN_URL,
            data={
                "client_id":     config.GMAIL_CLIENT_ID,
                "client_secret": config.GMAIL_CLIENT_SECRET,
                "refresh_token": config.GMAIL_REFRESH_TOKEN,
                "grant_type":    "refresh_token",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:
        log.error("Failed to refresh Gmail access token: %s", exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

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
    show_financing: bool = True,
    down_payment: int | None = None,
    num_vehicles: int = 1,
) -> bool:
    """
    Send an HTML email summary via Gmail API with the CSV attached.

    Returns True on success, False on failure or if conditions not met.
    Only sends when SEND_EMAIL=True (or force=True).
    email_to specifies the recipients for this profile's email.
    """
    if not config.SEND_EMAIL and not force:
        log.debug("Email skipped (SEND_EMAIL=False)")
        return False

    if not _is_configured():
        log.warning("Email not sent — Gmail OAuth credentials not configured (run setup_gmail_oauth.py)")
        return False

    recipients_list = email_to or []
    if not recipients_list:
        log.warning("Email not sent — no recipients configured")
        return False

    access_token = _get_access_token()
    if not access_token:
        return False

    subject = _build_subject(listings, price_drops, profile_label)
    html    = _build_html(listings, llm_result, price_drops, trends or {}, new_vins or set(),
                          profile_label, show_financing=show_financing, down_payment=down_payment,
                          num_vehicles=num_vehicles)

    from_addr = (
        f"{config.EMAIL_FROM_NAME} <{config.GMAIL_SENDER}>"
        if config.EMAIL_FROM_NAME
        else config.GMAIL_SENDER
    )

    # Build MIME message
    if csv_path and Path(csv_path).exists():
        msg = MIMEMultipart()
        msg.attach(MIMEText(html, "html", "utf-8"))
        try:
            with open(csv_path, "rb") as f:
                attachment = MIMEBase("text", "csv")
                attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=Path(csv_path).name,
            )
            msg.attach(attachment)
            log.debug("CSV attached: %s", Path(csv_path).name)
        except Exception as exc:
            log.warning("Could not attach CSV: %s", exc)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html, "html", "utf-8"))

    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(recipients_list)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    try:
        resp = requests.post(
            _SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
            timeout=20,
        )
        resp.raise_for_status()
        log.info("Email sent to %d recipient(s) via Gmail API", len(recipients_list))
        return True
    except requests.HTTPError as exc:
        body = resp.text[:300] if resp is not None else ""
        log.error("Gmail API HTTP error: %s — %s", exc, body)
    except Exception as exc:
        log.error("Email send failed: %s", exc)
    return False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_configured() -> bool:
    return bool(
        config.GMAIL_CLIENT_ID
        and config.GMAIL_CLIENT_SECRET
        and config.GMAIL_REFRESH_TOKEN
        and config.GMAIL_SENDER
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
    show_financing: bool = True,
    down_payment: int | None = None,
    num_vehicles: int = 1,
) -> str:
    run_time = datetime.now().strftime("%b %d, %Y %I:%M %p")

    # ── Build table listing set ───────────────────────────────────────────────
    # LLM top picks always lead the table (in LLM rank order), then fill the
    # remaining slots with non-pick listings sorted by score.
    if num_vehicles > 1:
        table_limit = 5   # per model cap for the fill section
        table_label = "Top 5 per Model"
    else:
        table_limit = 15
        table_label = "Top 15 Listings"

    vin_to_listing: dict[str, dict] = {r.get("vin"): r for r in listings if r.get("vin")}

    # 1. Seed the table with LLM picks (in rank order), skipping unknowns.
    llm_pick_order: list[str] = [v for v in (llm_result.top_pick_vins or []) if v and v in vin_to_listing]
    table_listings: list[dict] = [vin_to_listing[v] for v in llm_pick_order]
    table_vin_set: set[str] = set(llm_pick_order)

    # 2. Fill remaining slots with non-pick listings up to the per-model/total cap.
    if num_vehicles > 1:
        seen_counts: dict[tuple[str, str], int] = {}
        # Pre-count LLM picks toward their model quotas so picks don't consume
        # fill slots twice.
        for r in table_listings:
            key = (r.get("make") or "", r.get("model") or "")
            seen_counts[key] = seen_counts.get(key, 0) + 1
        for r in listings:
            if (r.get("vin") or "") in table_vin_set:
                continue
            key = (r.get("make") or "", r.get("model") or "")
            if seen_counts.get(key, 0) < table_limit:
                table_listings.append(r)
                table_vin_set.add(r.get("vin") or "")
                seen_counts[key] = seen_counts.get(key, 0) + 1
    else:
        for r in listings:
            if (r.get("vin") or "") not in table_vin_set:
                table_listings.append(r)
                table_vin_set.add(r.get("vin") or "")
            if len(table_listings) >= table_limit:
                break

    # ── Determine starred VINs ────────────────────────────────────────────────
    def _top_scored_vins(rows: list[dict], exclude: set[str], n: int) -> set[str]:
        result: set[str] = set()
        for r in sorted(rows, key=lambda x: -(x.get("value_score") or 0)):
            if len(result) >= n:
                break
            vin = r.get("vin")
            if vin and vin not in exclude:
                result.add(vin)
        return result

    if llm_result.top_pick_vins:
        llm_pick_set = set(llm_result.top_pick_vins)
        starred_vins: set[str] = {
            r.get("vin") for r in table_listings if r.get("vin") in llm_pick_set
        }
    else:
        # No LLM picks — fall back to top 3 by value score
        starred_vins = _top_scored_vins(table_listings, exclude=set(), n=3)

    drop_by_vin: dict[str, dict] = {d["vin"]: d for d in price_drops if d.get("vin")}
    new_vins = new_vins or set()

    parts = [
        "<html><body style='font-family:sans-serif;max-width:880px;margin:auto;color:#222;line-height:1.5'>",
        f"<h2 style='margin-bottom:4px'>{profile_label} — {run_time}</h2>",
        f"<p style='color:#555;margin-top:0'>Found <b>{len(listings)}</b> listings matching your filters.</p>",
    ]

    # ── Table ─────────────────────────────────────────────────────────────────
    parts.append(f"<h3 style='margin-bottom:4px'>{table_label}</h3>")
    parts.append(
        "<p style='font-size:12px;color:#666;margin-top:0'>"
        "<b>★</b> = LLM top pick (top value score if no LLM analysis) &nbsp;|&nbsp;"
        "▼ = price drop (▼ X% = tracked drop vs last run; ▼ Price Drop = Carvana badge) &nbsp;|&nbsp;"
        "<span style='background:#27ae60;color:white;font-size:11px;padding:1px 5px;"
        "border-radius:3px'>NEW</span> = first time seen or marked Recent by Carvana"
        "</p>"
    )
    financing_th = "<th>Est. Payment</th>" if show_financing else ""
    parts.append(
        "<table border='1' cellpadding='7' cellspacing='0' "
        "style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr style='background:#f0f0f0;text-align:left'>"
        f"<th>#</th><th>Vehicle</th><th>Color</th><th>Trim</th><th>Price</th>"
        f"<th>Mileage</th>{financing_th}<th>Score</th><th>Hybrid</th><th></th>"
        "</tr>"
    )

    for i, r in enumerate(table_listings, start=1):
        vin      = r.get("vin") or ""
        url      = r.get("url") or "#"
        price    = r.get("price") or 0
        mileage  = r.get("mileage")
        is_db_drop   = vin in drop_by_vin
        is_carvana_drop = bool(r.get("is_carvana_price_drop"))
        is_drop      = is_db_drop or is_carvana_drop
        is_pick      = vin in starred_vins
        is_new       = vin in new_vins or bool(r.get("is_recent"))

        row_bg   = ""
        position = f"<b>★ {i}</b>" if is_pick else str(i)

        if is_db_drop:
            drop_pct   = drop_by_vin[vin].get("drop_pct", "")
            price_cell = (
                f"<b>${price:,.0f}</b>"
                f"<br><span style='color:#27ae60;font-size:11px'>▼ {drop_pct}% drop</span>"
            )
        elif is_carvana_drop:
            price_cell = (
                f"<b>${price:,.0f}</b>"
                f"<br><span style='color:#27ae60;font-size:11px'>▼ Price Drop</span>"
            )
        else:
            price_cell = f"${price:,.0f}"

        hybrid_cell  = "<b style='color:#27ae60'>Yes</b>" if r.get("is_hybrid") else ""
        view_btn     = (
            f"<a href='{url}' style='background:#2980b9;color:white;padding:4px 10px;"
            f"border-radius:3px;text-decoration:none;font-size:12px;white-space:nowrap'>View</a>"
        )

        color_cell = (r.get("color_exterior") or "").strip()

        financing_td = (
            f"<td>${r.get('monthly_carvana') or r.get('monthly_estimated') or 0:,.0f}/mo</td>"
            if show_financing else ""
        )
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
            f"{financing_td}"
            f"<td style='text-align:center'>{int(r.get('value_score') or 0)}</td>"
            f"<td style='text-align:center'>{hybrid_cell}</td>"
            f"<td style='text-align:center'>{view_btn}</td>"
            f"</tr>"
        )

    parts.append("</table>")
    has_db_drops     = any(r.get("vin") in drop_by_vin for r in table_listings)
    has_carvana_drops = any(r.get("is_carvana_price_drop") for r in table_listings)
    if has_db_drops and has_carvana_drops:
        parts.append(
            "<p style='font-size:12px;color:#555;margin-top:4px'>"
            "▼ X% drops are relative to the previous tracker run. "
            "▼ Price Drop is Carvana's own badge (reduction from their listing history).</p>"
        )
    elif has_db_drops:
        parts.append(
            "<p style='font-size:12px;color:#555;margin-top:4px'>"
            "Price drops are relative to the previous tracker run.</p>"
        )
    elif has_carvana_drops:
        parts.append(
            "<p style='font-size:12px;color:#555;margin-top:4px'>"
            "▼ Price Drop indicates Carvana has reduced the listing price from their history.</p>"
        )
    if show_financing:
        _dp = down_payment if down_payment is not None else config.DOWN_PAYMENT
        parts.append(
            f"<p style='font-size:12px;color:#555;margin-top:4px'>"
            f"Est. Payment assumes ${_dp:,} down, {config.INTEREST_RATE}% APR, "
            f"{config.LOAN_TERM_MONTHS}-month term.</p>"
        )

    # ── Trim key ──────────────────────────────────────────────────────────────
    trim_key_html = _build_trim_key_html(table_listings)
    if trim_key_html:
        parts.append(trim_key_html)

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


# ── Trim key ─────────────────────────────────────────────────────────────────

# Per-vehicle trim descriptions keyed by (make_lower, model_lower).
# Each entry: (display_name, one-line description).
_TRIM_KEY_DATA: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("honda", "cr-v"): [
        ("LX",                  "Base trim — Honda Sensing, 7\" screen, push-button start"),
        ("EX",                  "Best gas value — sunroof, heated seats, 9\" screen (2023+)"),
        ("EX-L",                "Leather, wireless charging, power liftgate, 8-speaker audio"),
        ("Touring",             "Top pre-2023 gas — navigation, 9-speaker audio, 19\" wheels"),
        ("Hybrid EX",           "2021–22 hybrid entry — AWD standard, 212 hp, e:HEV system"),
        ("Hybrid EX-L",         "2021–22 hybrid — leather, full LED headlights, AWD standard"),
        ("Hybrid Touring",      "Top 2021–22 hybrid — wireless charging, hands-free liftgate"),
        ("Sport Hybrid",        "Best 2023+ hybrid value — AWD standard, 204 hp ⭐"),
        ("Sport-L Hybrid",      "2024+ premium hybrid — leather, 9\" screen, wireless charger"),
        ("Sport Touring Hybrid","Top CR-V — Bose audio, head-up display, Honda navigation"),
    ],
    ("toyota", "rav4"): [
        ("LE",                    "Base gas — Safety Sense 2.0, CarPlay, 7\" screen"),
        ("XLE",                   "Best gas value — moonroof, blind-spot, alloy wheels ⭐"),
        ("XLE Premium",           "Leatherette seats, larger screen, power liftgate"),
        ("Adventure",             "AWD standard, 120V outlet, sport-tuned suspension"),
        ("TRD Off-Road",          "AWD standard, all-terrain tires, off-road suspension"),
        ("Limited",               "Top gas — JBL audio, ventilated seats, surround-view camera"),
        ("Hybrid LE",             "Entry hybrid — AWD standard, 41/38 MPG, best EPA payback"),
        ("Hybrid XLE",            "Best overall RAV4 — AWD standard, most recommended ⭐"),
        ("Hybrid XLE Premium",    "Hybrid + leatherette, larger screen, heated seats"),
        ("Hybrid SE",             "Sport-tuned suspension hybrid variant"),
        ("Hybrid XSE",            "Sport + luxury hybrid combination"),
        ("Hybrid Limited",        "Top hybrid — JBL audio, ventilated/heated seats, full cluster"),
        ("Hybrid Woodland Edition","Adventure hybrid — all-terrain tires, bronze wheels (2023+)"),
    ],
    ("kia", "sportage"): [
        ("LX (2021–22)",          "4th gen — older platform, significantly inferior to 2023+ ⚠"),
        ("EX (2021–22)",          "4th gen mid-level — still older platform ⚠"),
        ("SX Turbo (2021–22)",    "4th gen top trim — 1.6T, 175 hp ⚠"),
        ("LX",                    "5th gen base — 8\" screen, 12.2\" cluster, ADAS, LED headlights"),
        ("EX",                    "Best 5th gen gas value — 12.3\" screen, wireless charging ⭐"),
        ("X-Line AWD",            "AWD standard, locking differential, off-road modes"),
        ("SX",                    "Panoramic sunroof, Harman Kardon audio — FWD only"),
        ("SX Prestige",           "SX + enhanced safety tech — FWD only"),
        ("X-Pro",                 "Best off-road — AWD, all-terrain tires, hill descent"),
        ("X-Pro Prestige",        "X-Pro + heated windshield, blind-spot view monitor"),
        ("Hybrid LX",             "Entry hybrid — 42/44 MPG FWD, excellent efficiency"),
        ("Hybrid EX",             "Best hybrid value — 12.3\" screen, wireless charging ⭐"),
        ("Hybrid X-Line AWD",     "Hybrid + AWD standard, off-road styling"),
        ("Hybrid SX Prestige",    "Top hybrid — panoramic sunroof, Harman Kardon, AWD standard"),
    ],
    ("subaru", "forester"): [
        ("Base",            "AWD standard — EyeSight ADAS; skip for Premium"),
        ("Premium",         "Best gas value — panoramic sunroof, heated seats, X-Mode ⭐"),
        ("Sport",           "Dual X-Mode (Snow/Dirt + Deep Snow/Mud), sport styling"),
        ("Limited",         "Leather seats, 8\" screen, dual-zone climate, power liftgate"),
        ("Touring",         "Top gas — Harman Kardon audio, navigation, heated rear seats"),
        ("Wilderness",      "Best off-road — 9.2\" clearance, all-terrain tires (2022+)"),
        ("Premium Hybrid",  "Best 2025 hybrid value — panoramic moonroof, wireless CarPlay ⭐"),
        ("Sport Hybrid",    "2025 — Harman Kardon 11-speaker, 19\" bronze wheels"),
        ("Limited Hybrid",  "2025 — heated steering wheel, 8-way power passenger seat"),
        ("Touring Hybrid",  "Top 2025 trim — 360° camera, ventilated seats, leather"),
    ],
    ("toyota", "grand highlander"): [
        ("Hybrid LE",          "2025 only entry trim — AWD standard, 12.3\" screen, 245 hp"),
        ("Hybrid XLE",         "Best value — moonroof, heated seats, wireless charging (FWD or AWD) ⭐"),
        ("Hybrid Limited",     "AWD standard — leather, ventilated seats, 360° surround camera"),
        ("Hybrid Nightshade",  "2025 only — Limited features + blacked-out exterior accents"),
        ("Hybrid MAX",         "⚠ OUT OF SCOPE — turbocharged 362 hp, worse MPG (26–27 combined)"),
    ],
}


def _build_trim_key_html(listings: list[dict]) -> str:
    """
    Build a compact trim-level key for every make/model present in `listings`.
    Returns an empty string if no matching data is found.
    """
    # Collect unique (make, model) pairs that appear in the listings.
    # Preserve original casing for display by tracking the first seen raw values.
    seen: list[tuple[str, str]] = []          # (make_lower, model_lower)
    seen_set: set[tuple[str, str]] = set()
    display_labels: dict[tuple[str, str], tuple[str, str]] = {}  # key → (make, model) display
    for r in listings:
        make_raw  = (r.get("make") or "").strip()
        model_raw = (r.get("model") or "").strip()
        key = (make_raw.lower(), model_raw.lower())
        if key not in seen_set and key in _TRIM_KEY_DATA:
            seen.append(key)
            seen_set.add(key)
            display_labels[key] = (make_raw, model_raw)

    if not seen:
        return ""

    parts = [
        "<div style='margin-top:24px'>",
        "<h3 style='margin-bottom:6px'>Trim Level Key</h3>",
        "<p style='font-size:12px;color:#666;margin-top:0;margin-bottom:10px'>"
        "Available trims for each vehicle in this search. ⭐ = recommended value trim. "
        "⚠ = flagged / out of scope.</p>",
    ]

    for make_key, model_key in seen:
        trims = _TRIM_KEY_DATA[(make_key, model_key)]
        make_display, model_display = display_labels[(make_key, model_key)]
        parts.append(
            f"<div style='margin-bottom:14px'>"
            f"<b style='font-size:13px'>{make_display} {model_display}</b>"
            f"<table style='font-size:12px;border-collapse:collapse;margin-top:4px;width:100%'>"
        )
        for trim_name, description in trims:
            row_style = "color:#c0392b" if "⚠" in trim_name or "⚠" in description else "color:#333"
            parts.append(
                f"<tr>"
                f"<td style='padding:2px 10px 2px 0;white-space:nowrap;font-weight:600;"
                f"{row_style};vertical-align:top;width:200px'>{trim_name}</td>"
                f"<td style='padding:2px 0;color:#555'>{description}</td>"
                f"</tr>"
            )
        parts.append("</table></div>")

    parts.append("</div>")
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
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+?)_",   r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code style='background:#eee;padding:1px 4px;border-radius:3px'>\1</code>", text)
    return text
