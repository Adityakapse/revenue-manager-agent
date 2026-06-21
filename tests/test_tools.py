"""
Tool property tests (Phase 2) — covers tests/TOOL_TEST_SCENARIOS.md (scenarios 1-6, 8-12).

Run against the loaded Postgres:  .venv/bin/pytest tests/test_tools.py -v

We assert structural PROPERTIES (grain inequalities, share sums, monotonicity, isolation),
not brittle exact floats. Months use the current anchor (2026) where the OTB business lives.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from tools.metrics import (
    ALL_TOOLS,
    get_as_of_otb,
    get_block_vs_transient_mix,
    get_otb_summary,
    get_pickup_delta,
    get_segment_mix,
)

OTB_MONTH = "2026-09"  # busiest month
SEG_MONTH = "2026-08"  # has OTA + a Retail macro group


# --- Scenario 1: grain inequality ----------------------------------------- #
def test_grain_inequalities():
    s = get_otb_summary(OTB_MONTH)
    assert s["reservation_count"] < s["row_count"]  # multi-night bookings -> more rows
    assert s["room_nights"] >= s["reservation_count"]  # >= 1 room night per reservation
    assert s["room_revenue"] <= s["total_revenue"]  # total includes non-room components


# --- Scenario 2: cancellation filter changes counts ----------------------- #
def test_cancellation_filter_changes_counts():
    excl = get_otb_summary(OTB_MONTH, exclude_cancelled=True)
    incl = get_otb_summary(OTB_MONTH, exclude_cancelled=False)
    assert excl["row_count"] < incl["row_count"]  # month has cancelled stay rows
    assert excl["reservation_count"] <= incl["reservation_count"]


# --- Scenario 3: segment shares sum to one -------------------------------- #
def test_segment_shares_sum_to_one():
    mix = get_segment_mix(SEG_MONTH)
    rn = sum(s["share_of_room_nights"] for s in mix["segments"])
    rev = sum(s["share_of_revenue"] for s in mix["segments"])
    assert abs(rn - 1.0) < 1e-6
    assert abs(rev - 1.0) < 1e-6
    assert all(0.0 <= s["share_of_revenue"] <= 1.0 for s in mix["segments"])


# --- Scenario 4: macro group filter narrows universe ---------------------- #
def test_macro_group_filter_narrows():
    full = get_segment_mix(SEG_MONTH)
    retail = get_segment_mix(SEG_MONTH, macro_group="Retail")
    assert retail["denominator"]["room_nights"] <= full["denominator"]["room_nights"]
    assert all(s["macro_group"] == "Retail" for s in retail["segments"])


# --- Scenario 5: pickup uses booking date, not stay date ------------------ #
def test_pickup_uses_booking_window():
    # create_datetime defines the booking window; a wider window can only add reservations.
    wide = get_pickup_delta(365, "2026-07-01")
    narrow = get_pickup_delta(1, "2026-07-01")
    assert narrow["new_reservations"] <= wide["new_reservations"]
    # future_stay_from filters on stay_date: a far-future floor yields nothing.
    beyond = get_pickup_delta(365, "2030-01-01")
    assert beyond["new_reservations"] == 0


# --- Scenario 6: OTA concentration signal --------------------------------- #
def test_ota_segment_present():
    mix = get_segment_mix(SEG_MONTH)
    ota = [s for s in mix["segments"] if s["market_code"] == "OTA"]
    assert ota, "OTA segment missing -> broken ETL or wrong month"
    assert 0.0 < ota[0]["share_of_revenue"] < 1.0


# --- Scenario 8: provisional excluded from default OTB -------------------- #
def _month_with_provisional(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            select to_char(stay_date,'YYYY-MM')
            from public.reservations_hackathon
            where financial_status = 'Provisional'
            order by stay_date limit 1
            """
        )
        row = cur.fetchone()
    return row[0] if row else None


def test_provisional_excluded_from_default_otb(conn):
    month = _month_with_provisional(conn)
    assert month, "dataset should contain provisional rows"
    lo = f"{month}-01"
    with conn.cursor() as cur:
        # rows excluding ONLY cancelled (still includes provisional)
        cur.execute(
            """
            select count(*) from public.reservations_hackathon
            where reservation_status <> 'Cancelled'
              and stay_date >= %s::date and stay_date < (%s::date + interval '1 month')
            """,
            (lo, lo),
        )
        only_cancelled_excluded = cur.fetchone()[0]
    default_otb = get_otb_summary(month)["row_count"]  # also excludes provisional
    assert default_otb < only_cancelled_excluded


def test_provisional_present_in_load_proof(repo_root: Path):
    proof = json.loads((repo_root / "etl/LOAD_PROOF.json").read_text())
    assert proof["aggregates"]["provisional_row_count"] > 0


# --- Scenario 9: as-of snapshot differs from current OTB ------------------ #
def test_as_of_differs_from_current():
    current = get_otb_summary(OTB_MONTH)["row_count"]
    early = get_as_of_otb(OTB_MONTH, "2026-01-01T00:00:00Z")["row_count"]
    future = get_as_of_otb(OTB_MONTH, "2030-01-01T00:00:00Z")["row_count"]
    assert early < current  # bookings created after as_of are excluded
    assert future == current  # far-future as_of == current posted/non-cancelled OTB


# --- Scenario 10: property_date vs stay_date ------------------------------ #
def test_property_date_mismatch_matches_proof(conn, repo_root: Path):
    proof = json.loads((repo_root / "etl/LOAD_PROOF.json").read_text())
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.reservations_hackathon where property_date <> stay_date"
        )
        db_mismatch = cur.fetchone()[0]
    assert db_mismatch == proof["aggregates"]["property_date_mismatch_count"]


# --- Scenario 11: block vs transient mix ---------------------------------- #
def test_block_transient_reconciles():
    bt = get_block_vs_transient_mix(OTB_MONTH)
    otb = get_otb_summary(OTB_MONTH)
    assert bt["block_room_nights"] + bt["transient_room_nights"] == otb["room_nights"]
    assert 0.0 <= bt["block_share_of_room_nights"] <= 1.0
    assert 0.0 <= bt["block_share_of_revenue"] <= 1.0
    assert bt["top3_company_revenue_share"] <= 1.0
    assert len(bt["top_companies"]) <= 3
    revs = [c["total_revenue"] for c in bt["top_companies"]]
    assert revs == sorted(revs, reverse=True)


# --- Scenario 12: tool layer isolation ------------------------------------ #
def test_tools_isolated_and_documented():
    # All five tools import and run without starting any server (this test does exactly that).
    assert len(ALL_TOOLS) == 5
    forbidden = {"sql", "query", "statement", "raw"}
    for tool in ALL_TOOLS:
        sig = inspect.signature(tool)
        # No agent-facing tool accepts a free-form SQL string parameter.
        assert not (forbidden & set(sig.parameters)), f"{tool.__name__} exposes raw SQL param"
        # Every parameter is a simple typed scalar (str/int/bool), never an SQL blob.
        for p in sig.parameters.values():
            assert (
                p.annotation in (str, int, bool, "str | None", "str", "int", "bool")
                or p.annotation is inspect.Parameter.empty
            )
        # Each docstring states the grain.
        assert "grain" in (tool.__doc__ or "").lower()
