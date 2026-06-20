"""
One-off exploration script (NOT part of the real ETL).

Purpose: the data site is client-rendered, so we must drive a real browser to see
what's on each page. This prints the rendered structure so we can design the scraper:
selectors, pagination, the list columns, detail-page fields, and the /verify counts.

Run:  .venv/bin/python etl/explore.py
"""

from playwright.sync_api import sync_playwright

BASE = "https://otel-hackathon-data-site.vercel.app"


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1) /verify — the counts + dataset_revision we must reconcile against.
        section("/verify  (rendered text)")
        page.goto(f"{BASE}/verify", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)  # let client JS finish computing checksums
        print(page.inner_text("body")[:3000])

        # 2) /reservations — list page: pagination + the columns shown.
        section("/reservations  (rendered text, first 2000 chars)")
        page.goto(f"{BASE}/reservations", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        print(page.inner_text("body")[:2000])

        section("/reservations  — links that point to a detail page")
        hrefs = page.eval_on_selector_all(
            "a[href*='/reservations/']",
            "els => els.map(e => e.getAttribute('href'))",
        )
        print(f"detail-link count on page 1: {len(hrefs)}")
        print("first 5 hrefs:", hrefs[:5])

        section("/reservations  — table HTML skeleton (headers + first row)")
        # Print header cells and the first data row to learn column order.
        headers = page.eval_on_selector_all(
            "th", "els => els.map(e => e.innerText.trim())"
        )
        print("table headers:", headers)
        first_row = page.eval_on_selector_all(
            "table tr:nth-child(1) td, tbody tr:first-child td",
            "els => els.map(e => e.innerText.trim())",
        )
        print("first data row cells:", first_row)

        # Look for pagination controls / URL param style.
        section("/reservations  — pagination hints")
        page2 = page.eval_on_selector_all(
            "a[href*='page'], button",
            "els => els.map(e => (e.getAttribute('href')||'') + ' | ' + e.innerText.trim()).slice(0,20)",
        )
        print("pagination-ish controls:", page2)

        # 3) A detail page — drill into the first reservation we found.
        if hrefs:
            detail_href = hrefs[0]
            detail_url = detail_href if detail_href.startswith("http") else BASE + detail_href
            section(f"DETAIL PAGE  {detail_url}  (rendered text)")
            page.goto(detail_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            print(page.inner_text("body")[:3500])

        # 4) /reference — lookup tables + macro group effective dates.
        section("/reference  (rendered text, first 3500 chars)")
        page.goto(f"{BASE}/reference", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        print(page.inner_text("body")[:3500])

        # 5) /changelog — note dataset revision history.
        section("/changelog  (rendered text, first 1500 chars)")
        page.goto(f"{BASE}/changelog", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        print(page.inner_text("body")[:1500])

        browser.close()


if __name__ == "__main__":
    main()
