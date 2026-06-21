"""
ETL — LOAD step.

Idempotent load into Postgres: truncate-and-reload so re-running yields an IDENTICAL
database (no duplicates). Loads lookups first (foreign-key parents), then the fact table,
then appends one load_manifest row whose row_hash equals the dataset fingerprint that
/verify and scripts/compute_load_fingerprint.py compute.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any

import psycopg

DEFAULT_DATABASE_URL = "postgresql://hackathon:hackathon@localhost:5432/hotel_hackathon"

# Truncate every data table in one shot; CASCADE + RESTART IDENTITY make it repeatable.
_TRUNCATE = """
truncate table
  public.reservations_hackathon,
  public.market_macro_group_history,
  public.room_type_lookup,
  public.rate_plan_lookup,
  public.market_code_lookup,
  public.channel_code_lookup,
  public.load_manifest
restart identity cascade;
"""

# Fact-table columns we insert (reservation_stay_id is GENERATED ALWAYS — never inserted).
_FACT_COLUMNS = [
    "reservation_id",
    "arrival_date",
    "departure_date",
    "stay_date",
    "property_date",
    "reservation_status",
    "financial_status",
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
    "daily_room_revenue_before_tax",
    "daily_total_revenue_before_tax",
    "nights",
    "adr_room",
    "lead_time",
    "company_name",
    "travel_agent_name",
]


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def connect(database_url: str | None = None):
    return psycopg.connect(database_url or get_database_url())


def _insert_many(cur, table: str, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    cols = ", ".join(columns)
    placeholders = ", ".join([f"%({c})s" for c in columns])
    cur.executemany(
        f"insert into public.{table} ({cols}) values ({placeholders})",
        rows,
    )


def _compute_pair_hash(cur) -> str:
    """
    SHA-256 of sorted 'reservation_id|stay_date|financial_status' lines — byte-identical
    to scripts/compute_load_fingerprint.fetch_pair_hash and the /verify checksum.
    """
    cur.execute(
        """
        select reservation_id, stay_date::text, financial_status
        from public.reservations_hackathon
        order by reservation_id, stay_date, financial_status
        """
    )
    lines = [f"{r}|{s}|{fin}" for r, s, fin in cur.fetchall()]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def load_all(
    transformed: dict[str, Any],
    dataset_revision: str,
    source_url: str,
    scraped_at: datetime | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Run the full idempotent load. Returns a small summary (counts + row_hash)."""
    ref = transformed["reference"]
    facts = transformed["fact_rows"]
    scraped_at = scraped_at or datetime.now(UTC)

    with connect(database_url) as conn:
        with conn.cursor() as cur:
            # 1) Wipe (idempotency) ...
            cur.execute(_TRUNCATE)

            # 2) ... load FK parents first ...
            _insert_many(
                cur,
                "room_type_lookup",
                ["space_type", "room_class", "display_name", "number_of_rooms"],
                ref["room_types"],
            )
            _insert_many(
                cur,
                "rate_plan_lookup",
                ["rate_plan_code", "plan_family", "is_commissionable"],
                ref["rate_plans"],
            )
            _insert_many(
                cur,
                "market_code_lookup",
                ["market_code", "market_name", "macro_group", "description"],
                ref["markets"],
            )
            _insert_many(
                cur,
                "channel_code_lookup",
                ["channel_code", "channel_name", "channel_group"],
                ref["channels"],
            )
            _insert_many(
                cur,
                "market_macro_group_history",
                ["market_code", "valid_from", "valid_to", "macro_group"],
                ref["macro_history"],
            )

            # 3) ... then the fact table.
            _insert_many(cur, "reservations_hackathon", _FACT_COLUMNS, facts)

            # 4) Fingerprint the loaded fact table and record one manifest row.
            row_hash = _compute_pair_hash(cur)
            cur.execute(
                """
                insert into public.load_manifest
                  (dataset_revision, scraped_at, source_url, row_hash)
                values (%s, %s, %s, %s)
                """,
                (dataset_revision, scraped_at, source_url, row_hash),
            )
        conn.commit()

    return {
        "fact_rows_loaded": len(facts),
        "reservations_loaded": len({r["reservation_id"] for r in facts}),
        "row_hash": row_hash,
        "dataset_revision": dataset_revision,
    }
