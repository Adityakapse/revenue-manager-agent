"""
ETL orchestrator: scrape -> transform -> load, then write etl/SCRAPE_MANIFEST.json.

Usage:
  .venv/bin/python -m etl.run_etl              # full run (all 254 reservations)
  .venv/bin/python -m etl.run_etl --limit 5    # quick smoke run (first 5 detail pages)

Reads DATABASE_URL from .env (falls back to the local docker Postgres).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from etl.load import load_all
from etl.scrape import BASE, scrape_all
from etl.transform import transform_all

ETL_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = ETL_DIR / "SCRAPE_MANIFEST.json"
CACHE_PATH = ETL_DIR / ".cache" / "raw_scrape.json"  # raw scrape, gitignored


def _ids_sha256(reservation_ids: list[str]) -> str:
    """SHA-256 of sorted reservation_id lines (one per line) — matches /verify + the fingerprint script."""
    payload = "\n".join(sorted(reservation_ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="Only scrape the first N detail pages (smoke testing)")
    parser.add_argument("--use-cache", action="store_true",
                        help="Skip scraping; reuse the cached raw scrape from a previous run")
    args = parser.parse_args()

    load_dotenv(ETL_DIR.parent / ".env")

    if args.use_cache and CACHE_PATH.exists():
        print(f"1/4  Extract — reusing cached scrape ({CACHE_PATH})")
        scraped = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    else:
        print("1/4  Extract — scraping the data site (this drives a real browser)...")
        scraped = scrape_all(limit_detail=args.limit)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(scraped, indent=2), encoding="utf-8")
        print(f"     cached raw scrape -> {CACHE_PATH}")
    print(f"     anchor_date={scraped['anchor_date']}  revision={scraped['dataset_revision']}  "
          f"reservations={len(scraped['reservation_ids'])}")

    print("2/4  Transform — typing + enforcing reservation x stay_date grain...")
    transformed = transform_all(scraped)
    print(f"     fact rows={len(transformed['fact_rows'])}  "
          f"lookups={{room:{len(transformed['reference']['room_types'])}, "
          f"rate:{len(transformed['reference']['rate_plans'])}, "
          f"market:{len(transformed['reference']['markets'])}, "
          f"channel:{len(transformed['reference']['channels'])}, "
          f"macro:{len(transformed['reference']['macro_history'])}}}")

    print("3/4  Load — idempotent truncate-and-reload into Postgres...")
    summary = load_all(
        transformed,
        dataset_revision=scraped["dataset_revision"],
        source_url=f"{BASE}/reservations",
        scraped_at=datetime.now(timezone.utc),
        database_url=os.environ.get("DATABASE_URL"),
    )
    print(f"     loaded {summary['fact_rows_loaded']} fact rows / "
          f"{summary['reservations_loaded']} reservations")
    print(f"     row_hash={summary['row_hash']}")

    print("4/4  Writing etl/SCRAPE_MANIFEST.json ...")
    pages_scraped = -(-len(scraped["reservation_ids"]) // 100)  # ceil division, 100/page
    manifest = {
        "anchor_date": scraped["anchor_date"],
        "pages_scraped": pages_scraped,
        "reservation_ids_count": len(scraped["reservation_ids"]),
        "reservation_ids_sha256": _ids_sha256(scraped["reservation_ids"]),
        "dataset_revision": scraped["dataset_revision"],
        "source_url": f"{BASE}/reservations",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"     wrote {MANIFEST_PATH}")
    print("\nDone. Next: reconcile with /verify and generate etl/LOAD_PROOF.json.")


if __name__ == "__main__":
    main()
