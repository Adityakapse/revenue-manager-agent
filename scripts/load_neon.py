"""
One-shot loader for a remote Postgres (e.g. Neon): apply schema + views, load the cached
dataset, and confirm the fingerprint matches etl/LOAD_PROOF.json.

Run from a machine with outbound :5432 (your own terminal — agent/CI sandboxes often allow
only HTTPS/443 egress, so they cannot reach a remote DB):

    cd "<repo>"
    DATABASE_URL="postgresql://...neon.../neondb?sslmode=require" .venv/bin/python -m scripts.load_neon
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

from etl.load import load_all
from etl.run_etl import CACHE_PATH
from etl.scrape import BASE, scrape_all
from etl.transform import transform_all

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL to the remote (Neon) connection string first.")

    # 1) schema + views
    for f in ("schema.sql", "sql/views.sql"):
        sql = (ROOT / f).read_text(encoding="utf-8")
        with psycopg.connect(url, autocommit=True) as conn:
            for stmt in sql.split(";"):
                if stmt.strip():
                    conn.execute(stmt)
        print(f"  applied {f}")

    # 2) load the same dataset our proofs describe (cache), or scrape if the cache is gone
    if CACHE_PATH.exists():
        scraped = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        print(f"  using cached scrape (anchor {scraped['anchor_date']})")
    else:
        print("  no cache found -> scraping fresh ...")
        scraped = scrape_all()

    transformed = transform_all(scraped)
    summary = load_all(
        transformed,
        dataset_revision=scraped["dataset_revision"],
        source_url=f"{BASE}/reservations",
        database_url=url,
    )
    print(f"  loaded {summary['fact_rows_loaded']} rows / {summary['reservations_loaded']} reservations")
    print(f"  row_hash: {summary['row_hash']}")

    # 3) reconcile with the committed proof
    proof = json.loads((ROOT / "etl/LOAD_PROOF.json").read_text(encoding="utf-8"))
    matches = summary["row_hash"] == proof["reservation_stay_status_sha256"]
    print(f"\n  MATCHES etl/LOAD_PROOF.json: {matches}")
    if not matches:
        print("  (mismatch -> the remote DB differs from your committed proof; investigate before deploy)")


if __name__ == "__main__":
    main()
