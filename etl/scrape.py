"""
ETL — EXTRACT step.

Drives a real (headless) Chromium browser via Playwright to read the client-rendered
data site, because a plain HTTP fetch only sees an empty JavaScript shell.

It produces RAW string records (no typing/cleaning yet — that's transform.py's job):

    {
      "anchor_date": "2026-06-15",
      "dataset_revision": "2026.06.12.2",
      "reservation_ids": ["R0001", ...],          # sorted, distinct — proves full pagination
      "reservations": [                            # one entry per reservation (booking)
        {"reservation_id": "R0001", "fields": {...}, "stay_rows": [{...}, ...]},
        ...
      ],
      "reference": {                               # the 5 lookup tables
        "room_types": [...], "markets": [...], "channels": [...],
        "rate_plans": [...], "macro_history": [...]
      },
    }

Everything here is read-only against a public website.
"""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Page, sync_playwright

BASE = "https://otel-hackathon-data-site.vercel.app"

# The booking-level labels shown in the detail page "RESERVATION FIELDS" block.
# We read them as alternating label/value text lines, keeping only known labels.
DETAIL_FIELD_LABELS = {
    "arrival_date",
    "departure_date",
    "nights",
    "reservation_status",
    "create_datetime",
    "cancellation_datetime",
    "guest_country",
    "is_block",
    "is_walk_in",
    "number_of_spaces",
    "space_type",
    "market_code",
    "channel_code",
    "source_name",
    "rate_plan_code",
    "commercial_rate_code",
    "adr_room",
    "lead_time",
    "company_name",
    "travel_agent_name",
}

_RENDER_WAIT_MS = 1800  # let client JS finish painting after navigation


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _goto(page: Page, url: str) -> None:
    """Navigate and wait for the client-side render to settle."""
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(_RENDER_WAIT_MS)


def _read_table(page: Page, nth: int = 0) -> dict[str, list]:
    """
    Read the nth <table> on the page into {headers: [...], rows: [[cell,...], ...]}.
    Works regardless of CSS classes — we only rely on th/td structure.
    """
    return page.evaluate(
        """(n) => {
            const t = document.querySelectorAll('table')[n];
            if (!t) return {headers: [], rows: []};
            const headers = [...t.querySelectorAll('th')].map(e => e.innerText.trim());
            const rows = [...t.querySelectorAll('tbody tr')]
                .map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim()))
                .filter(cells => cells.length > 0);
            return {headers, rows};
        }""",
        nth,
    )


def _table_to_dicts(table: dict[str, list]) -> list[dict[str, str]]:
    """Turn {headers, rows} into a list of {header_lower: cell} dicts."""
    headers = [h.lower() for h in table["headers"]]
    out: list[dict[str, str]] = []
    for row in table["rows"]:
        out.append({headers[i]: row[i] for i in range(min(len(headers), len(row)))})
    return out


# --------------------------------------------------------------------------- #
# Reference tables (/reference) — 5 lookup tables behind tabs
# --------------------------------------------------------------------------- #
def scrape_reference(page: Page) -> tuple[dict[str, list], str]:
    """Click each /reference tab and read its table. Returns (reference, dataset_revision)."""
    _goto(page, f"{BASE}/reference")

    body = page.inner_text("body")
    m = re.search(r"Dataset revision\s+([0-9.]+)", body)
    dataset_revision = m.group(1) if m else ""

    reference: dict[str, list] = {}
    tab_to_key = {
        "Room types": "room_types",
        "Markets": "markets",
        "Channels": "channels",
        "Rate plans": "rate_plans",
        "Macro history": "macro_history",
    }
    for tab_label, key in tab_to_key.items():
        # Tabs are buttons; click then let the table swap in.
        page.get_by_text(tab_label, exact=True).first.click()
        page.wait_for_timeout(600)
        reference[key] = _table_to_dicts(_read_table(page, nth=0))
    return reference, dataset_revision


# --------------------------------------------------------------------------- #
# Reservation list (/reservations) — paginate via "Next →" to collect every id
# --------------------------------------------------------------------------- #
def scrape_reservation_ids(page: Page) -> tuple[list[str], str, int]:
    """
    Return (sorted distinct reservation_ids, anchor_date, declared_total).
    Pages by clicking "Next →" until we've collected the declared total (or Next stops working).
    """
    _goto(page, f"{BASE}/reservations")

    header = page.inner_text("body")
    total_m = re.search(r"(\d+)\s+reservations", header)
    declared_total = int(total_m.group(1)) if total_m else 0
    anchor_m = re.search(r"as of\s+(\d{4}-\d{2}-\d{2})", header)
    anchor_date = anchor_m.group(1) if anchor_m else ""

    ids: list[str] = []
    seen: set[str] = set()
    for _page_num in range(1, 50):  # generous safety cap
        page.wait_for_selector("a[href*='/reservations/']", timeout=30000)
        page_ids = page.eval_on_selector_all(
            "a[href*='/reservations/']",
            "els => els.map(e => e.getAttribute('href').split('/').pop())",
        )
        new = [i for i in page_ids if i not in seen]
        for i in new:
            seen.add(i)
            ids.append(i)

        # Stop when we have them all.
        if declared_total and len(seen) >= declared_total:
            break

        # Click "Next →"; stop if it's gone/disabled or the page didn't change.
        nxt = page.locator("button:has-text('Next'), a:has-text('Next')").first
        if nxt.count() == 0 or (nxt.get_attribute("disabled") is not None):
            break
        first_before = page_ids[0] if page_ids else None
        nxt.click()
        try:
            page.wait_for_function(
                """(prev) => {
                    const a = document.querySelector("a[href*='/reservations/']");
                    return a && a.getAttribute('href').split('/').pop() !== prev;
                }""",
                arg=first_before,
                timeout=15000,
            )
        except Exception:
            break  # no change -> we were on the last page

    return sorted(seen), anchor_date, declared_total


# --------------------------------------------------------------------------- #
# Reservation detail (/reservations/<id>) — full record + per-night stay rows
# --------------------------------------------------------------------------- #
def scrape_detail(page: Page, reservation_id: str) -> dict[str, Any]:
    """Scrape one reservation's booking fields + its per-night stay rows."""
    _goto(page, f"{BASE}/reservations/{reservation_id}")

    # Booking-level fields: alternating label/value lines between the markers.
    lines = [ln.strip() for ln in page.inner_text("body").split("\n") if ln.strip()]
    fields: dict[str, str] = {}
    i = 0
    while i < len(lines) - 1:
        label = lines[i].lower()
        if label in DETAIL_FIELD_LABELS:
            fields[label] = lines[i + 1]
            i += 2
        else:
            i += 1

    # Per-night stay rows live in the page's table.
    stay_rows = _table_to_dicts(_read_table(page, nth=0))

    return {"reservation_id": reservation_id, "fields": fields, "stay_rows": stay_rows}


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def scrape_all(limit_detail: int | None = None, headless: bool = True) -> dict[str, Any]:
    """
    Full extract. `limit_detail` caps how many detail pages we fetch (for quick validation);
    None means scrape every reservation.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        reference, dataset_revision = scrape_reference(page)
        reservation_ids, anchor_date, declared_total = scrape_reservation_ids(page)

        ids_to_fetch = reservation_ids if limit_detail is None else reservation_ids[:limit_detail]
        reservations = []
        for n, rid in enumerate(ids_to_fetch, start=1):
            reservations.append(scrape_detail(page, rid))
            if n % 25 == 0:
                print(f"  ...scraped {n}/{len(ids_to_fetch)} detail pages")

        browser.close()

    return {
        "anchor_date": anchor_date,
        "dataset_revision": dataset_revision,
        "declared_total": declared_total,
        "reservation_ids": reservation_ids,
        "reservations": reservations,
        "reference": reference,
    }


if __name__ == "__main__":
    # Quick validation run: reference + first 2 detail pages only.
    import json

    result = scrape_all(limit_detail=2)
    print("anchor_date     :", result["anchor_date"])
    print("dataset_revision:", result["dataset_revision"])
    print("declared_total  :", result["declared_total"])
    print(
        "ids scraped     :",
        len(result["reservation_ids"]),
        "->",
        result["reservation_ids"][:3],
        "...",
        result["reservation_ids"][-3:],
    )
    print("\nreference row counts:")
    for k, v in result["reference"].items():
        print(f"  {k:14s}: {len(v)} rows -> sample {v[0] if v else None}")
    print("\nfirst detail record:")
    print(json.dumps(result["reservations"][0], indent=2))
