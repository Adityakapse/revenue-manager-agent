"""
ETL — TRANSFORM step.

Takes the RAW string records from scrape.py and produces clean, correctly-typed rows
that match schema.sql, enforcing the fact-table grain (one row per reservation x stay_date).

Key cleaning rules learned from the data site:
  - "—" (em dash) means NULL  -> None
  - "true"/"false" strings     -> Python bool
  - numbers may contain commas -> stripped before parsing
  - timestamps are ISO-8601 UTC ("...Z")
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

NULL_TOKENS = {"—", "-", "", "n/a", "none", "null"}


# --------------------------------------------------------------------------- #
# Field coercion helpers
# --------------------------------------------------------------------------- #
def _nullable(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return None if v.lower() in NULL_TOKENS else v


def to_str(value: str | None) -> str | None:
    return _nullable(value)


def to_int(value: str | None) -> int | None:
    v = _nullable(value)
    return None if v is None else int(v.replace(",", ""))


def to_num(value: str | None) -> float | None:
    v = _nullable(value)
    return None if v is None else float(v.replace(",", ""))


def to_bool(value: str | None) -> bool:
    v = _nullable(value)
    return str(v).strip().lower() == "true"


def to_date(value: str | None) -> date | None:
    v = _nullable(value)
    return None if v is None else date.fromisoformat(v)


def to_ts(value: str | None) -> datetime | None:
    """Parse ISO-8601, treating trailing 'Z' as UTC."""
    v = _nullable(value)
    if v is None:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# Reference (lookup) tables
# --------------------------------------------------------------------------- #
def transform_reference(reference: dict[str, list[dict]]) -> dict[str, list[dict]]:
    room_types = [
        {
            "space_type": r["space_type"],
            "room_class": r["room_class"],
            "display_name": r["display_name"],
            "number_of_rooms": to_int(r["number_of_rooms"]),
        }
        for r in reference["room_types"]
    ]
    rate_plans = [
        {
            "rate_plan_code": r["rate_plan_code"],
            "plan_family": r["plan_family"],
            "is_commissionable": to_bool(r["is_commissionable"]),
        }
        for r in reference["rate_plans"]
    ]
    markets = [
        {
            "market_code": r["market_code"],
            "market_name": r["market_name"],
            "macro_group": r["macro_group"],
            "description": to_str(r.get("description")),
        }
        for r in reference["markets"]
    ]
    channels = [
        {
            "channel_code": r["channel_code"],
            "channel_name": r["channel_name"],
            "channel_group": r["channel_group"],
        }
        for r in reference["channels"]
    ]
    macro_history = [
        {
            "market_code": r["market_code"],
            "valid_from": to_date(r["valid_from"]),
            "valid_to": to_date(r["valid_to"]),  # "—" -> None (open-ended)
            "macro_group": r["macro_group"],
        }
        for r in reference["macro_history"]
    ]
    return {
        "room_types": room_types,
        "rate_plans": rate_plans,
        "markets": markets,
        "channels": channels,
        "macro_history": macro_history,
    }


# --------------------------------------------------------------------------- #
# Fact table — one row per reservation x stay_date
# --------------------------------------------------------------------------- #
def transform_reservations(reservations: list[dict]) -> list[dict[str, Any]]:
    """
    Expand each reservation into one fact row per stay-night, stamping the booking-level
    fields (constant across nights) onto each per-night stay row.
    """
    fact_rows: list[dict[str, Any]] = []
    for res in reservations:
        f = res["fields"]
        booking = {
            "reservation_id": res["reservation_id"],
            "arrival_date": to_date(f["arrival_date"]),
            "departure_date": to_date(f["departure_date"]),
            "reservation_status": f["reservation_status"],
            "create_datetime": to_ts(f["create_datetime"]),
            "cancellation_datetime": to_ts(f.get("cancellation_datetime")),
            "guest_country": to_str(f.get("guest_country")),
            "is_block": to_bool(f["is_block"]),
            "is_walk_in": to_bool(f["is_walk_in"]),
            "number_of_spaces": to_int(f["number_of_spaces"]),
            "space_type": f["space_type"],
            "market_code": f["market_code"],
            "channel_code": f["channel_code"],
            "source_name": f["source_name"],
            # The UI label "Commercial rate code" maps to column rate_plan_code (per changelog).
            "rate_plan_code": f["rate_plan_code"],
            "nights": to_int(f["nights"]),
            "adr_room": to_num(f["adr_room"]),
            "lead_time": to_int(f["lead_time"]),
            "company_name": to_str(f.get("company_name")),
            "travel_agent_name": to_str(f.get("travel_agent_name")),
        }
        for sr in res["stay_rows"]:
            fact_rows.append(
                {
                    **booking,
                    "stay_date": to_date(sr["stay_date"]),
                    "property_date": to_date(sr["property_date"]),
                    "financial_status": sr["financial_status"],
                    "daily_room_revenue_before_tax": to_num(sr["daily_room_revenue_before_tax"]),
                    "daily_total_revenue_before_tax": to_num(sr["daily_total_revenue_before_tax"]),
                }
            )
    return fact_rows


def transform_all(scrape_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference": transform_reference(scrape_result["reference"]),
        "fact_rows": transform_reservations(scrape_result["reservations"]),
    }
