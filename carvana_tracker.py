#!/usr/bin/env python3
"""
Carvana SUV Tracker
====================
Periodically searches Carvana for Honda CR-V, Toyota RAV4,
Subaru Forester, and Kia Sportage listings (2021-2025),
then outputs a sorted/analyzed CSV and optionally emails you.

Dependencies:
    pip install playwright requests schedule pandas tabulate
    playwright install chromium

Usage:
    python carvana_tracker.py            # Run once immediately
    python carvana_tracker.py --schedule # Run every N hours on a loop
    python carvana_tracker.py --email    # Also send email summary

Config:  Edit the CONFIG block below before running.
"""

import json
import base64
import csv
import time
import os
import argparse
import logging
from datetime import datetime
from pathlib import Path

# ──────────────────────────────────────────────
#  CONFIG — Edit this section before running
# ──────────────────────────────────────────────

CONFIG = {
    # Your Phoenix, AZ zip code (Carvana uses this for shipping cost estimates)
    "zip_code": "85001",

    # How often to re-check (hours). Only used with --schedule flag.
    "check_interval_hours": 6,

    # Where to save the CSV output
    "output_dir": "./carvana_results",

    # ── Vehicles to track ──────────────────────
    # Each entry: (make, model, min_year, max_year)
    # Comment out any you don't want
    "vehicles": [
        ("Honda",   "CR-V",      2021, 2025),
        ("Toyota",  "RAV4",      2021, 2025),
        ("Subaru",  "Forester",  2021, 2025),
        ("Kia",     "Sportage",  2021, 2025),
    ],

    # ── Filters ────────────────────────────────
    "max_price":    45000,   # Skip listings above this price
    "max_mileage":  80000,   # Skip listings above this mileage
    "min_year":     2021,    # Global minimum year
    "max_year":     2025,    # Global maximum year

    # ── Monthly payment estimate ───────────────
    # Carvana shows its own payment; we also calc a rough estimate
    "down_payment":     3000,   # Your expected down payment ($)
    "interest_rate":    7.5,    # APR % (check current rates)
    "loan_term_months": 60,     # Loan length in months

    # ── Email alerts (optional) ────────────────
    # Set SEND_EMAIL = True and fill in credentials to get emailed results
    "send_email":       False,
    "email_from":       "you@gmail.com",
    "email_to":         "you@gmail.com",
    "email_password":   "",   # Gmail App Password (not your login password)
                              # Generate at: myaccount.google.com/apppasswords
    # Alert me if a new listing appears below this price:
    "alert_price_threshold": 32000,

    # ── Scraping behavior ──────────────────────
    # Be a good citizen — don't hammer Carvana's servers
    "delay_between_requests": 4,   # seconds between page loads
    "headless": True,              # False = show browser window (useful for debugging)
    "timeout_seconds": 30,
}

# ──────────────────────────────────────────────
#  END CONFIG
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


# ── URL Builder ────────────────────────────────────────────────────────────────

def build_carvana_url(make: str, model: str, min_year: int, max_year: int) -> str:
    """
    Builds a Carvana search URL with base64-encoded filter parameters.
    Carvana encodes its filters as JSON -> base64 in the cvnaid param.
    """
    filters = {
        "filters": {
            "makes": [{"name": make, "models": [{"name": model}]}],
            "year": {"min": min_year, "max": max_year},
        }
    }
    encoded = base64.b64encode(json.dumps(filters, separators=(',', ':')).encode()).decode()
    return f"https://www.carvana.com/cars/filters?cvnaid={encoded}"


# ── Monthly Payment Calculator ─────────────────────────────────────────────────

def estimate_monthly_payment(price: float, down: float, apr: float, months: int) -> float:
    """Standard amortization formula."""
    principal = price - down
    if principal <= 0:
        return 0.0
    monthly_rate = (apr / 100) / 12
    if monthly_rate == 0:
        return principal / months
    payment = principal * (monthly_rate * (1 + monthly_rate) ** months) / ((1 + monthly_rate) ** months - 1)
    return round(payment, 2)


# ── Scraper ────────────────────────────────────────────────────────────────────

def scrape_carvana(make: str, model: str, min_year: int, max_year: int) -> list[dict]:
    """
    Uses Playwright (headless Chromium) to load Carvana search results
    and extract listing data from the page's embedded JSON state.

    Carvana renders via React and embeds vehicle data in a __NEXT_DATA__
    or window.__STATE__ script tag — we parse that directly instead of
    scraping HTML elements, which is more stable across page redesigns.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    url = build_carvana_url(make, model, min_year, max_year)
    log.info(f"Searching Carvana: {year_range(min_year, max_year)} {make} {model}")
    log.info(f"  URL: {url}")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["headless"])
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=CONFIG["timeout_seconds"] * 1000)
            time.sleep(2)  # Let React hydrate

            # Strategy 1: Parse __NEXT_DATA__ JSON (most reliable)
            next_data = page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }""")

            if next_data:
                parsed = json.loads(next_data)
                vehicles = extract_from_next_data(parsed, make, model)
                results.extend(vehicles)
                log.info(f"  Found {len(vehicles)} listings via __NEXT_DATA__")

            # Strategy 2: Parse Apollo/GraphQL cache embedded in page
            if not results:
                apollo_data = page.evaluate("""() => {
                    for (const key of Object.keys(window)) {
                        if (key.startsWith('__apollo') || key === '__APOLLO_STATE__') {
                            return JSON.stringify(window[key]);
                        }
                    }
                    return null;
                }""")
                if apollo_data:
                    vehicles = extract_from_apollo(json.loads(apollo_data), make, model)
                    results.extend(vehicles)
                    log.info(f"  Found {len(vehicles)} listings via Apollo cache")

            # Strategy 3: Fall back to DOM scraping of listing cards
            if not results:
                vehicles = scrape_listing_cards(page, make, model)
                results.extend(vehicles)
                log.info(f"  Found {len(vehicles)} listings via DOM scraping")

        except PWTimeout:
            log.warning(f"  Timed out loading {url}")
        except Exception as e:
            log.error(f"  Error scraping {make} {model}: {e}")
        finally:
            browser.close()

    time.sleep(CONFIG["delay_between_requests"])
    return results


def extract_from_next_data(data: dict, make: str, model: str) -> list[dict]:
    """Extract vehicle listings from Next.js page data."""
    listings = []
    try:
        # Navigate the nested structure — path varies by Carvana version
        props = data.get("props", {})
        page_props = props.get("pageProps", {})

        # Try several known paths
        vehicles_raw = (
            page_props.get("vehicles") or
            page_props.get("inventory", {}).get("vehicles") or
            page_props.get("initialData", {}).get("vehicles") or
            []
        )

        for v in vehicles_raw:
            listing = normalize_vehicle(v, make, model)
            if listing:
                listings.append(listing)
    except Exception as e:
        log.debug(f"extract_from_next_data error: {e}")
    return listings


def extract_from_apollo(data: dict, make: str, model: str) -> list[dict]:
    """Extract from Apollo GraphQL cache."""
    listings = []
    try:
        for key, val in data.items():
            if isinstance(val, dict) and val.get("__typename") in ("Vehicle", "Car", "InventoryItem"):
                listing = normalize_vehicle(val, make, model)
                if listing:
                    listings.append(listing)
    except Exception as e:
        log.debug(f"extract_from_apollo error: {e}")
    return listings


def scrape_listing_cards(page, make: str, model: str) -> list[dict]:
    """
    DOM fallback: scrape the visible listing cards.
    Selectors may need updating if Carvana redesigns their UI.
    """
    listings = []
    try:
        # Wait for listing cards to appear
        page.wait_for_selector('[data-qa="vehicle-card"], .vehicle-card, [class*="VehicleCard"]', timeout=10000)

        cards = page.query_selector_all('[data-qa="vehicle-card"], .vehicle-card, [class*="VehicleCard"]')
        log.info(f"  Found {len(cards)} DOM cards")

        for card in cards:
            try:
                title = safe_text(card, '[data-qa="vehicle-card-title"], h2, h3')
                price_text = safe_text(card, '[data-qa="vehicle-card-price"], [class*="price"]')
                mileage_text = safe_text(card, '[data-qa="vehicle-card-mileage"], [class*="mileage"]')
                monthly_text = safe_text(card, '[class*="monthly"], [class*="payment"]')
                link_el = card.query_selector('a')
                link = "https://www.carvana.com" + link_el.get_attribute('href') if link_el else ""

                price = parse_price(price_text)
                mileage = parse_mileage(mileage_text)
                monthly = parse_price(monthly_text)

                if not title or price is None:
                    continue

                year = extract_year_from_title(title)

                listing = {
                    "year": year,
                    "make": make,
                    "model": model,
                    "trim": extract_trim(title, make, model),
                    "price": price,
                    "mileage": mileage,
                    "monthly_carvana": monthly,
                    "shipping": None,  # Not available in card view
                    "vin": "",
                    "url": link,
                    "scraped_at": datetime.now().isoformat(),
                }
                listings.append(listing)
            except Exception as e:
                log.debug(f"  Card parse error: {e}")
    except Exception as e:
        log.debug(f"scrape_listing_cards error: {e}")
    return listings


def normalize_vehicle(v: dict, make: str, model: str) -> dict | None:
    """Normalize a raw vehicle dict into our standard schema."""
    try:
        price = v.get("price") or v.get("listPrice") or v.get("salePrice") or 0
        if isinstance(price, dict):
            price = price.get("amount") or price.get("value") or 0
        price = float(str(price).replace(",", "").replace("$", "")) if price else None

        mileage = v.get("mileage") or v.get("miles") or 0
        mileage = int(str(mileage).replace(",", "")) if mileage else None

        year = v.get("year") or v.get("modelYear") or 0
        year = int(year) if year else None

        trim = v.get("trim") or v.get("trimLevel") or ""
        vin = v.get("vin") or v.get("stockNumber") or ""

        monthly = v.get("monthlyPayment") or v.get("estimatedMonthlyPayment") or None
        if isinstance(monthly, dict):
            monthly = monthly.get("amount")
        monthly = float(monthly) if monthly else None

        shipping = v.get("shippingFee") or v.get("deliveryFee") or v.get("transportationFee") or None
        if isinstance(shipping, dict):
            shipping = shipping.get("amount")
        shipping = float(shipping) if shipping else None

        slug = v.get("slug") or v.get("vehicleUrl") or ""
        url = f"https://www.carvana.com/vehicle/{slug}" if slug and not slug.startswith("http") else slug

        if not price or price <= 0:
            return None

        return {
            "year": year,
            "make": make,
            "model": model,
            "trim": trim,
            "price": price,
            "mileage": mileage,
            "monthly_carvana": monthly,
            "shipping": shipping,
            "vin": vin,
            "url": url,
            "scraped_at": datetime.now().isoformat(),
        }
    except Exception:
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_text(el, selector: str) -> str:
    try:
        found = el.query_selector(selector)
        return found.inner_text().strip() if found else ""
    except Exception:
        return ""

def parse_price(text: str) -> float | None:
    import re
    nums = re.findall(r'[\d,]+', str(text).replace("$", ""))
    if nums:
        return float(nums[0].replace(",", ""))
    return None

def parse_mileage(text: str) -> int | None:
    import re
    nums = re.findall(r'[\d,]+', str(text))
    if nums:
        return int(nums[0].replace(",", ""))
    return None

def extract_year_from_title(title: str) -> int | None:
    import re
    m = re.search(r'\b(20\d{2})\b', title)
    return int(m.group(1)) if m else None

def extract_trim(title: str, make: str, model: str) -> str:
    return title.replace(str(extract_year_from_title(title) or ""), "").replace(make, "").replace(model, "").strip()

def year_range(min_y: int, max_y: int) -> str:
    return f"{min_y}–{max_y}"


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze_and_filter(listings: list[dict]) -> list[dict]:
    """Apply filters and add calculated fields."""
    out = []
    for r in listings:
        price = r.get("price") or 0
        mileage = r.get("mileage") or 0
        year = r.get("year") or 0

        # Apply filters
        if CONFIG["max_price"] and price > CONFIG["max_price"]:
            continue
        if CONFIG["max_mileage"] and mileage > CONFIG["max_mileage"]:
            continue
        if year and year < CONFIG["min_year"]:
            continue
        if year and year > CONFIG["max_year"]:
            continue

        # Calculate our own monthly payment estimate
        r["monthly_estimated"] = estimate_monthly_payment(
            price,
            CONFIG["down_payment"],
            CONFIG["interest_rate"],
            CONFIG["loan_term_months"],
        )

        # Price per mile (rough value indicator — lower is better for newer cars)
        r["price_per_mile"] = round(price / mileage, 2) if mileage and mileage > 0 else None

        # Total cost with shipping
        shipping = r.get("shipping") or 0
        r["total_with_shipping"] = price + shipping

        # Flag hybrids in trim
        trim_lower = (r.get("trim") or "").lower()
        r["is_hybrid"] = any(kw in trim_lower for kw in ["hybrid", "hev", "phev", "prime"])

        out.append(r)

    # Sort by price ascending
    out.sort(key=lambda x: x.get("price") or 999999)
    return out


def print_summary(listings: list[dict]):
    """Print a readable table to the terminal."""
    try:
        from tabulate import tabulate
        rows = []
        for r in listings:
            rows.append([
                f"{r.get('year', '?')} {r.get('make', '')} {r.get('model', '')}",
                r.get("trim", "")[:20],
                f"${r.get('price', 0):,.0f}",
                f"{r.get('mileage', 0):,.0f} mi",
                f"${r.get('monthly_estimated', 0):,.0f}/mo",
                f"${r.get('shipping') or 0:,.0f}" if r.get("shipping") is not None else "n/a",
                "✓" if r.get("is_hybrid") else "",
            ])
        headers = ["Vehicle", "Trim", "Price", "Mileage", "Est. Payment", "Shipping", "Hybrid"]
        print("\n" + tabulate(rows, headers=headers, tablefmt="rounded_outline"))
        print(f"\n  {len(listings)} listings found | Down: ${CONFIG['down_payment']:,} | "
              f"{CONFIG['interest_rate']}% APR | {CONFIG['loan_term_months']}mo term\n")
    except ImportError:
        for r in listings:
            print(f"  {r['year']} {r['make']} {r['model']} {r.get('trim','')} | "
                  f"${r['price']:,.0f} | {r.get('mileage',0):,.0f} mi | "
                  f"${r['monthly_estimated']:,.0f}/mo")


def save_csv(listings: list[dict], run_ts: str):
    """Save results to a timestamped CSV file."""
    out_dir = Path(CONFIG["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = out_dir / f"carvana_{run_ts}.csv"

    fieldnames = [
        "year", "make", "model", "trim", "price", "mileage",
        "monthly_carvana", "monthly_estimated", "shipping",
        "total_with_shipping", "price_per_mile", "is_hybrid",
        "vin", "url", "scraped_at"
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(listings)

    log.info(f"Saved {len(listings)} listings → {filename}")

    # Also overwrite a "latest" file for easy access
    latest = out_dir / "carvana_latest.csv"
    with open(latest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(listings)

    return filename


def send_email_summary(listings: list[dict], new_deals: list[dict]):
    """Send an email with the summary and any price alerts."""
    if not CONFIG["send_email"] or not CONFIG["email_password"]:
        return

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    subject = f"Carvana Tracker Update — {len(listings)} listings found"
    if new_deals:
        subject = f"🚨 {len(new_deals)} deals under ${CONFIG['alert_price_threshold']:,}! " + subject

    body_lines = [f"<h2>Carvana SUV Tracker — {datetime.now().strftime('%b %d, %Y %I:%M %p')}</h2>"]
    body_lines.append(f"<p>Found <b>{len(listings)}</b> listings matching your criteria.</p>")

    if new_deals:
        body_lines.append(f"<h3>🚨 Price Alerts — Under ${CONFIG['alert_price_threshold']:,}</h3><ul>")
        for r in new_deals:
            body_lines.append(
                f"<li><b>{r['year']} {r['make']} {r['model']} {r.get('trim','')}</b> — "
                f"${r['price']:,.0f} | {r.get('mileage',0):,.0f} mi | "
                f"<a href='{r.get('url','')}'>View on Carvana</a></li>"
            )
        body_lines.append("</ul>")

    body_lines.append("<h3>All Listings</h3><table border='1' cellpadding='5' style='border-collapse:collapse'>")
    body_lines.append("<tr><th>Vehicle</th><th>Trim</th><th>Price</th><th>Mileage</th><th>Est. Payment</th><th>Hybrid</th><th>Link</th></tr>")
    for r in listings[:30]:  # Cap at 30 to avoid huge emails
        body_lines.append(
            f"<tr><td>{r['year']} {r['make']} {r['model']}</td>"
            f"<td>{r.get('trim','')[:18]}</td>"
            f"<td>${r['price']:,.0f}</td>"
            f"<td>{r.get('mileage',0):,.0f}</td>"
            f"<td>${r.get('monthly_estimated',0):,.0f}/mo</td>"
            f"<td>{'Yes' if r.get('is_hybrid') else ''}</td>"
            f"<td><a href='{r.get('url','')}'>View</a></td></tr>"
        )
    body_lines.append("</table>")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = CONFIG["email_from"]
    msg["To"] = CONFIG["email_to"]
    msg.attach(MIMEText("\n".join(body_lines), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(CONFIG["email_from"], CONFIG["email_password"])
            server.sendmail(CONFIG["email_from"], CONFIG["email_to"], msg.as_string())
        log.info(f"Email sent to {CONFIG['email_to']}")
    except Exception as e:
        log.error(f"Email failed: {e}")


# ── Main Run ────────────────────────────────────────────────────────────────────

def run_once():
    """Execute one full search-and-analyze cycle."""
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log.info(f"{'='*55}")
    log.info(f"  Carvana Tracker run started — {datetime.now().strftime('%b %d %Y %I:%M %p')}")
    log.info(f"{'='*55}")

    all_listings = []

    for make, model, min_year, max_year in CONFIG["vehicles"]:
        raw = scrape_carvana(make, model, min_year, max_year)
        all_listings.extend(raw)

    if not all_listings:
        log.warning("No listings returned. Carvana may have blocked the request.")
        log.warning("Try: setting headless=False in CONFIG to debug, or use the Apify option.")
        return

    filtered = analyze_and_filter(all_listings)
    print_summary(filtered)
    save_csv(filtered, run_ts)

    price_threshold = CONFIG.get("alert_price_threshold", 99999)
    new_deals = [r for r in filtered if (r.get("price") or 999999) < price_threshold]
    if new_deals:
        log.info(f"  {len(new_deals)} listings under ${price_threshold:,} — price alert triggered!")

    if CONFIG.get("send_email"):
        send_email_summary(filtered, new_deals)

    log.info(f"Run complete. {len(filtered)} listings saved.\n")
    return filtered


def main():
    parser = argparse.ArgumentParser(description="Carvana SUV Tracker")
    parser.add_argument("--schedule", action="store_true", help="Run on a repeating schedule")
    parser.add_argument("--email", action="store_true", help="Enable email alerts this run")
    args = parser.parse_args()

    if args.email:
        CONFIG["send_email"] = True

    if args.schedule:
        try:
            import schedule
        except ImportError:
            log.error("Install schedule: pip install schedule")
            return

        interval = CONFIG["check_interval_hours"]
        log.info(f"Scheduled mode: running every {interval} hours. Press Ctrl+C to stop.")
        run_once()  # Run immediately on start
        schedule.every(interval).hours.do(run_once)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_once()


if __name__ == "__main__":
    main()
