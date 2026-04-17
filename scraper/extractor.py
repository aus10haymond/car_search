"""
Page data extraction strategies for Carvana search result pages.

Priority order:
  1. Schema.org ld+json (application/ld+json script tags) — current primary strategy
  2. __NEXT_DATA__ JSON  (legacy Next.js pages renderer)
  3. Apollo/GraphQL cache
  4. DOM scraping via BeautifulSoup (last resort)

All strategies feed into normalize_vehicle() which returns a standard dict.
"""

import json
import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


# ── Strategy 1: Schema.org ld+json ───────────────────────────────────────────

def extract_from_schema_org(html: str) -> list[dict]:
    """
    Extract vehicle data from <script type="application/ld+json"> blocks.
    Carvana embeds one block per listing card with @type=Vehicle.
    Returns [] if none found.
    """
    blocks = re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    results = []
    for block in blocks:
        try:
            data = json.loads(block)
            if data.get("@type") == "Vehicle":
                results.append(data)
        except json.JSONDecodeError:
            continue
    log.debug("Schema.org ld+json vehicle count: %d", len(results))
    return results


# ── Strategy 2: __NEXT_DATA__ ─────────────────────────────────────────────────

def extract_from_next_data(html: str) -> list[dict]:
    """
    Parse the __NEXT_DATA__ JSON blob from the page HTML.
    Navigate: props -> pageProps -> (vehicles | inventory.vehicles | initialData.vehicles)
    Returns a list of raw vehicle dicts. Returns [] if not found.
    """
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        log.debug("__NEXT_DATA__ script tag not found")
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        log.debug("Failed to parse __NEXT_DATA__ JSON: %s", exc)
        return []

    page_props = data.get("props", {}).get("pageProps", {})
    vehicles_raw = (
        page_props.get("vehicles")
        or page_props.get("inventory", {}).get("vehicles")
        or page_props.get("initialData", {}).get("vehicles")
        or _deep_search_vehicles(page_props)
        or []
    )

    log.debug("__NEXT_DATA__ raw vehicle count: %d", len(vehicles_raw))
    return vehicles_raw if isinstance(vehicles_raw, list) else []


def _deep_search_vehicles(obj, depth: int = 0) -> list | None:
    """Recursively search for a 'vehicles' list up to 4 levels deep."""
    if depth > 4 or not isinstance(obj, dict):
        return None
    for key, val in obj.items():
        if key == "vehicles" and isinstance(val, list) and val:
            return val
        result = _deep_search_vehicles(val, depth + 1)
        if result:
            return result
    return None


# ── Strategy 2: Apollo/GraphQL cache ─────────────────────────────────────────

def extract_from_apollo_cache(html: str) -> list[dict]:
    """
    Use regex to find __APOLLO_STATE__ or similar window variable.
    Filter keys where __typename is Vehicle, Car, or InventoryItem.
    Returns [] if not found.
    """
    match = re.search(
        r'window\.__(?:APOLLO_STATE__|apollo\w*)\s*=\s*(\{.*?\});\s*(?:window|</script)',
        html,
        re.DOTALL,
    )
    if not match:
        # Broader fallback: look for any __APOLLO_STATE__
        match = re.search(r'"__APOLLO_STATE__"\s*:\s*(\{.*?\})\s*[,}]', html, re.DOTALL)

    if not match:
        log.debug("Apollo cache not found in page")
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        log.debug("Failed to parse Apollo cache JSON: %s", exc)
        return []

    vehicle_types = {"Vehicle", "Car", "InventoryItem"}
    results = [
        val for val in data.values()
        if isinstance(val, dict) and val.get("__typename") in vehicle_types
    ]
    log.debug("Apollo cache vehicle count: %d", len(results))
    return results


# ── Strategy 3: DOM scraping ──────────────────────────────────────────────────

def extract_from_dom(html: str) -> list[dict]:
    """
    Parse listing cards using BeautifulSoup.
    Target selectors (in priority order):
      - [data-qa="vehicle-card"]
      - .vehicle-card
      - [class*="VehicleCard"]
    Returns [] if no cards found.
    """
    soup = BeautifulSoup(html, "html.parser")

    cards = (
        soup.select('[data-qa="vehicle-card"]')
        or soup.select(".vehicle-card")
        or soup.select('[class*="VehicleCard"]')
    )

    if not cards:
        log.debug("No vehicle cards found in DOM")
        return []

    log.debug("DOM found %d cards", len(cards))
    results = []
    for card in cards:
        try:
            title = _card_text(card, [
                '[data-qa="vehicle-card-title"]', "h2", "h3",
            ])
            price_text = _card_text(card, [
                '[data-qa="vehicle-card-price"]', '[class*="price"]',
            ])
            mileage_text = _card_text(card, [
                '[data-qa="vehicle-card-mileage"]', '[class*="mileage"]',
            ])
            monthly_text = _card_text(card, [
                '[class*="monthly"]', '[class*="payment"]',
            ])
            link_tag = card.find("a", href=True)
            href = str(link_tag["href"]) if link_tag else ""
            url = (
                f"https://www.carvana.com{href}"
                if href and not href.startswith("http")
                else href
            )

            results.append({
                "title":    title,
                "price":    _parse_price(price_text),
                "mileage":  _parse_mileage(mileage_text),
                "monthly":  _parse_price(monthly_text),
                "url":      url,
                "_source":  "dom",
            })
        except Exception as exc:
            log.debug("DOM card parse error: %s", exc)

    return results


# ── Normalizer ────────────────────────────────────────────────────────────────

def normalize_vehicle(raw: dict, make: str, model: str, strategy: str) -> dict | None:
    """
    Converts a raw vehicle dict (from any strategy) into the standard schema.
    Returns None if the listing is missing a price or cannot be parsed.
    """
    try:
        # ── price ─────────────────────────────────────────────────────────────
        # Schema.org: offers.price  |  legacy: price / listPrice / salePrice
        offers = raw.get("offers") or {}
        price = (
            offers.get("price")
            or raw.get("price")
            or raw.get("listPrice")
            or raw.get("salePrice")
            or raw.get("purchasePrice")
            or 0
        )
        if isinstance(price, dict):
            price = price.get("amount") or price.get("value") or 0
        price = _to_float(price)
        if not price or price <= 0:
            return None

        # ── mileage ───────────────────────────────────────────────────────────
        # Schema.org: mileageFromOdometer  |  legacy: mileage / miles
        mileage = (
            raw.get("mileageFromOdometer")
            or raw.get("mileage")
            or raw.get("miles")
            or raw.get("odometer")
            or None
        )
        mileage = _to_int(mileage)

        # ── year ──────────────────────────────────────────────────────────────
        # Schema.org: modelDate  |  legacy: year / modelYear
        year = raw.get("modelDate") or raw.get("year") or raw.get("modelYear") or None
        if year is None and raw.get("title"):
            year = _year_from_title(raw["title"])
        if year is None and raw.get("name"):
            year = _year_from_title(raw["name"])
        year = _to_int(year)

        # ── trim ──────────────────────────────────────────────────────────────
        # Schema.org: embedded in description "Used YEAR MAKE MODEL TRIM with X miles"
        trim = raw.get("trim") or raw.get("trimLevel") or raw.get("trimName") or ""
        if not trim:
            desc = raw.get("description") or raw.get("name") or ""
            trim = _trim_from_description(desc, make, model, year)
        if not trim and raw.get("title"):
            trim = _trim_from_title(raw["title"], make, model, year)

        # ── vin ───────────────────────────────────────────────────────────────
        # Schema.org: vehicleIdentificationNumber  |  legacy: vin / stockNumber
        vin = (
            raw.get("vehicleIdentificationNumber")
            or raw.get("vin")
            or raw.get("stockNumber")
            or raw.get("vehicleId")
            or raw.get("sku")
            or ""
        )

        # ── monthly payment (Carvana's quoted figure) ─────────────────────────
        monthly = (
            raw.get("monthlyPayment")
            or raw.get("estimatedMonthlyPayment")
            or raw.get("monthly")
            or None
        )
        if isinstance(monthly, dict):
            monthly = monthly.get("amount") or monthly.get("value")
        monthly = _to_float(monthly)

        # ── URL ───────────────────────────────────────────────────────────────
        # Schema.org: offers.url  |  legacy: slug / vehicleUrl / url
        url = (
            offers.get("url")
            or raw.get("slug")
            or raw.get("vehicleUrl")
            or raw.get("url")
            or ""
        )
        if url and not url.startswith("http"):
            url = f"https://www.carvana.com/vehicle/{url}"

        # ── colours ───────────────────────────────────────────────────────────
        color_ext = (
            raw.get("exteriorColor")
            or raw.get("color")
            or raw.get("colorExterior")
            or ""
        )

        # ── purchase in progress ─────────────────────────────────────────────
        # Schema.org offers.availability; also check various legacy status fields.
        availability = (offers.get("availability") or "").lower()
        status = (
            raw.get("status")
            or raw.get("inventoryStatus")
            or raw.get("listingStatus")
            or ""
        ).lower()
        explicit_flag = bool(
            raw.get("purchaseInProgress")
            or raw.get("purchase_in_progress")
            or raw.get("isPurchaseInProgress")
        )
        purchase_in_progress = (
            explicit_flag
            or "progress" in availability
            or "progress" in status
            or "pending"  in status
            or "reserved" in status
            or "hold"     in status
        )

        log.debug(
            "Normalized via %s: %s %s %s %s — $%s%s",
            strategy, year, make, model, trim, price,
            " [PURCHASE IN PROGRESS]" if purchase_in_progress else "",
        )

        return {
            "vin":                   str(vin),
            "year":                  year,
            "make":                  make,
            "model":                 model,
            "trim":                  str(trim).strip(),
            "price":                 price,
            "mileage":               mileage,
            "monthly_carvana":       monthly,
            "color_exterior":        str(color_ext).strip(),
            "url":                   url,
            "purchase_in_progress":  purchase_in_progress,
            "extraction_strategy":   strategy,
            "scraped_at":            datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        log.debug("normalize_vehicle error (%s): %s", strategy, exc)
        return None


# ── Orchestrator ──────────────────────────────────────────────────────────────

def _extract_purchase_in_progress_slugs(html: str) -> set[str]:
    """
    Find vehicle cards in the search results page that carry a
    'Purchase in Progress' indicator in the rendered DOM.

    Carvana renders this as a visible badge/text on the card, e.g.:
      <span>Purchase In Progress</span>
    or via data-qa / class attributes.

    Returns a set of URL slugs (the last path segment of /vehicle/<slug>)
    for matching vehicles so callers can flag those listings.
    """
    soup = BeautifulSoup(html, "html.parser")
    slugs: set[str] = set()

    def _slug_from_node(node) -> str | None:
        """Walk up the DOM tree to find the nearest /vehicle/ link."""
        for _ in range(15):
            if node is None:
                return None
            link = node.find("a", href=lambda h: h and "/vehicle/" in h)
            if link:
                return str(link["href"]).rstrip("/").split("/")[-1].split("?")[0] or None
            node = node.parent
        return None

    # ── Text-node match ("Purchase In Progress" visible text) ────────────────
    for text_node in soup.find_all(
        string=re.compile(r"purchase\s+in\s+progress", re.IGNORECASE)
    ):
        slug = _slug_from_node(text_node.parent)
        if slug:
            slugs.add(slug)

    # ── Attribute-based match (data-qa, data-testid, class names) ────────────
    attr_patterns = (
        '[data-qa*="progress"]',
        '[data-qa*="in-progress"]',
        '[data-testid*="progress"]',
        '[data-testid*="in-progress"]',
        '[class*="in-progress"]',
        '[class*="inProgress"]',
        '[class*="purchaseInProgress"]',
    )
    for selector in attr_patterns:
        for el in soup.select(selector):
            slug = _slug_from_node(el)
            if slug:
                slugs.add(slug)

    if slugs:
        log.debug("DOM purchase-in-progress slugs found: %s", slugs)
    return slugs


def _extract_monthly_from_dom(html: str) -> dict[str, float]:
    """
    Scrape Carvana's rendered monthly payment values from the search results page.

    Carvana renders: <div data-testid="monthly-payment" ...>$893/mo</div>
    inside each vehicle card. For each element, walk up the DOM tree to find
    the nearest ancestor that contains a /vehicle/ link, and use the slug
    from that URL as the key.

    Returns a dict of vehicle URL slug → monthly payment (float).
    """
    soup = BeautifulSoup(html, "html.parser")
    elements = soup.select('[data-testid="monthly-payment"]')
    if not elements:
        log.debug("No [data-testid=monthly-payment] elements found in DOM")
        return {}

    result: dict[str, float] = {}
    for el in elements:
        val = _parse_price(el.get_text())
        if val is None:
            continue
        # Walk up ancestors to find the card container that has a /vehicle/ link
        slug = None
        node = el.parent
        for _ in range(12):  # cap traversal depth
            if node is None:
                break
            link = node.find("a", href=lambda h: h and "/vehicle/" in h)
            if link:
                slug = str(link["href"]).rstrip("/").split("/")[-1].split("?")[0]
                break
            node = node.parent
        if slug:
            result[slug] = val

    log.debug("DOM monthly payment map: %d slug→value entries", len(result))
    return result


def extract_listings(html: str, make: str, model: str) -> list[dict]:
    """
    Try all strategies in priority order.
    Returns normalized listings from the first strategy that yields results.
    Always attempts a DOM pass to backfill Carvana's monthly payment figure.
    """
    listings: list[dict] = []

    for strategy_fn, strategy_name in [
        (extract_from_schema_org,   "schema_org"),
        (extract_from_next_data,    "next_data"),
        (extract_from_apollo_cache, "apollo"),
        (extract_from_dom,          "dom"),
    ]:
        raw_list = strategy_fn(html)
        if raw_list:
            normalized = [
                normalize_vehicle(r, make, model, strategy_name)
                for r in raw_list
            ]
            valid = [v for v in normalized if v is not None]
            if valid:
                log.info(
                    "Extracted %d listings via %s for %s %s",
                    len(valid), strategy_name, make, model,
                )
                listings = valid
                break
            log.debug(
                "%s returned %d raw records but 0 valid after normalization",
                strategy_name, len(raw_list),
            )

    if not listings:
        log.warning("All extraction strategies failed for %s %s", make, model)
        return []

    # Backfill Carvana's monthly payment from the rendered DOM
    if any(not v.get("monthly_carvana") for v in listings):
        monthly_map = _extract_monthly_from_dom(html)
        if monthly_map:
            filled = 0
            for listing in listings:
                if listing.get("monthly_carvana"):
                    continue
                slug = (listing.get("url") or "").rstrip("/").split("/")[-1].split("?")[0]
                if slug and slug in monthly_map:
                    listing["monthly_carvana"] = monthly_map[slug]
                    filled += 1
            if filled:
                log.info("Backfilled monthly_carvana for %d/%d listings from DOM", filled, len(listings))
            else:
                log.debug("DOM monthly map built but no slugs matched listing URLs")

    # Flag any listings the DOM identifies as purchase-in-progress that the
    # JSON strategies may have missed.
    pip_slugs = _extract_purchase_in_progress_slugs(html)
    if pip_slugs:
        newly_flagged = 0
        for listing in listings:
            slug = (listing.get("url") or "").rstrip("/").split("/")[-1].split("?")[0]
            if slug and slug in pip_slugs and not listing.get("purchase_in_progress"):
                listing["purchase_in_progress"] = True
                newly_flagged += 1
        total_pip = sum(1 for v in listings if v.get("purchase_in_progress"))
        if newly_flagged:
            log.info(
                "DOM flagged %d additional purchase-in-progress listing(s) (%d total)",
                newly_flagged, total_pip,
            )

    return listings


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_price(text: str) -> float | None:
    nums = re.findall(r"[\d,]+", str(text).replace("$", ""))
    return float(nums[0].replace(",", "")) if nums else None


def _parse_mileage(text: str) -> int | None:
    nums = re.findall(r"[\d,]+", str(text))
    return int(nums[0].replace(",", "")) if nums else None


def _year_from_title(title: str) -> int | None:
    m = re.search(r"\b(20\d{2})\b", title)
    return int(m.group(1)) if m else None


def _trim_from_title(title: str, make: str, model: str, year: int | None) -> str:
    result = title
    for token in [str(year or ""), make, model]:
        result = result.replace(token, "")
    return result.strip()


def _trim_from_description(desc: str, make: str, model: str, year: int | None) -> str:
    """
    Extract trim from Schema.org description like:
      'Used 2021 Toyota RAV4 XLE Premium with 47863 miles - $27,990'
    Strips the known prefix and ' with N miles...' suffix.
    """
    if not desc:
        return ""
    # Remove 'Used YEAR MAKE MODEL ' prefix
    pattern = rf"(?:Used\s+)?{re.escape(str(year or ''))}\s*{re.escape(make)}\s*{re.escape(model)}\s*"
    result = re.sub(pattern, "", desc, flags=re.IGNORECASE).strip()
    # Remove ' with N miles...' suffix
    result = re.sub(r"\s+with\s+[\d,]+\s+miles.*$", "", result, flags=re.IGNORECASE).strip()
    return result


def _card_text(card, selectors: list[str]) -> str:
    for sel in selectors:
        el = card.select_one(sel)
        if el:
            return el.get_text(strip=True)
    return ""
