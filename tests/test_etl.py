"""
ETL property tests (Phase 1) — covers tests/ETL_TEST_SCENARIOS.md from the brief.

Run AFTER a successful load:  .venv/bin/pytest tests/test_etl.py -v

These assert the load is structurally correct and reconciles with the SCRAPE_MANIFEST
(which in turn must match the data site's /verify page).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _ids_sha256(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Scenario 1 — Lookup row counts
# --------------------------------------------------------------------------- #
def test_lookup_row_counts(conn):
    """The five lookup tables must have the exact counts the brief/ /verify specify."""
    expected = {
        "room_type_lookup": 3,
        "rate_plan_lookup": 8,
        "market_code_lookup": 10,
        "market_macro_group_history": 11,
        "channel_code_lookup": 4,
    }
    with conn.cursor() as cur:
        for table, want in expected.items():
            cur.execute(f"select count(*) from public.{table}")
            got = cur.fetchone()[0]
            assert got == want, f"{table}: expected {want}, got {got}"


# --------------------------------------------------------------------------- #
# Scenario 2 — Fact-table grain uniqueness
# --------------------------------------------------------------------------- #
def test_no_duplicate_reservation_stay_pairs(conn):
    """Grain is one row per (reservation_id, stay_date): no duplicates allowed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select count(*) from (
              select reservation_id, stay_date
              from public.reservations_hackathon
              group by reservation_id, stay_date
              having count(*) > 1
            ) dups
            """
        )
        assert cur.fetchone()[0] == 0


# --------------------------------------------------------------------------- #
# Scenario 3 — Manifest <-> DB reconciliation
# --------------------------------------------------------------------------- #
def test_manifest_matches_db(conn, repo_root: Path):
    """
    SCRAPE_MANIFEST.json must agree with the loaded DB:
      - reservation_ids_count == count(distinct reservation_id)
      - reservation_ids_sha256 == sha256 of the DB's sorted distinct ids
      - a load_manifest row exists with the manifest's dataset_revision
    """
    manifest = json.loads((repo_root / "etl/SCRAPE_MANIFEST.json").read_text())

    with conn.cursor() as cur:
        cur.execute("select distinct reservation_id from public.reservations_hackathon")
        db_ids = [r[0] for r in cur.fetchall()]

        assert manifest["reservation_ids_count"] == len(db_ids)
        assert manifest["reservation_ids_sha256"] == _ids_sha256(db_ids)

        cur.execute(
            "select count(*) from public.load_manifest where dataset_revision = %s",
            (manifest["dataset_revision"],),
        )
        assert cur.fetchone()[0] >= 1


# --------------------------------------------------------------------------- #
# Scenario 4 (bonus) — Stay-row expansion equals nights
# --------------------------------------------------------------------------- #
def test_multi_night_expansion(conn):
    """At least one multi-night reservation expands to exactly `nights` stay rows."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select count(*) from (
              select reservation_id, nights, count(*) as stay_rows
              from public.reservations_hackathon
              group by reservation_id, nights
              having nights > 1 and count(*) = nights
            ) ok
            """
        )
        assert cur.fetchone()[0] >= 1
