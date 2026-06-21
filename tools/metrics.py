"""
The five required Revenue Manager tools (Phase 2).

GRAIN CONTRACT (the thing that makes wrong answers hard):
  - row_count         = number of stay-date ROWS (reservation x stay_date grain)
  - reservation_count = count(distinct reservation_id)
  - room_nights       = sum(number_of_spaces)                 [rooms x nights]
  - room_revenue      = sum(daily_room_revenue_before_tax)    [room only]
  - total_revenue     = sum(daily_total_revenue_before_tax)   [room + extras]

Default OTB universe = Posted + non-cancelled (vw_stay_night_base).
The model passes only simple, typed arguments; it never supplies SQL. All queries are
parameterized and read from the semantic VIEWS, never the raw fact table.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tools.db import _num, month_bounds, query, query_one

LONDON = ZoneInfo("Europe/London")


# --------------------------------------------------------------------------- #
# 1. OTB summary
# --------------------------------------------------------------------------- #
def get_otb_summary(stay_month: str, exclude_cancelled: bool = True) -> dict:
    """On-the-books summary for a calendar month of STAY dates (stay_month='YYYY-MM').

    Default universe is vw_stay_night_base (Posted, non-cancelled). With
    exclude_cancelled=False, cancelled rows are included (still Posted only).

    GRAIN: row_count counts stay-date ROWS and is NOT a reservation count;
    reservation_count = count(distinct reservation_id); room_nights = sum(number_of_spaces).
    Returns: stay_month, row_count, reservation_count, room_nights, room_revenue,
    total_revenue, exclude_cancelled.
    """
    lo, hi = month_bounds(stay_month)
    view = "vw_stay_night_base" if exclude_cancelled else "vw_stay_night_posted"
    row = query_one(
        f"""
        select
          count(*)                                       as row_count,
          count(distinct reservation_id)                 as reservation_count,
          coalesce(sum(number_of_spaces), 0)             as room_nights,
          coalesce(sum(daily_room_revenue_before_tax),0) as room_revenue,
          coalesce(sum(daily_total_revenue_before_tax),0) as total_revenue
        from public.{view}
        where stay_date >= %(lo)s and stay_date < %(hi)s
        """,
        {"lo": lo, "hi": hi},
    )
    return {
        "stay_month": stay_month,
        "row_count": int(row["row_count"]),
        "reservation_count": int(row["reservation_count"]),
        "room_nights": int(row["room_nights"]),
        "room_revenue": _num(row["room_revenue"]),
        "total_revenue": _num(row["total_revenue"]),
        "exclude_cancelled": exclude_cancelled,
    }


# --------------------------------------------------------------------------- #
# 2. Segment mix
# --------------------------------------------------------------------------- #
def get_segment_mix(stay_month: str, macro_group: str | None = None) -> dict:
    """Segment mix for a stay month using vw_segment_stay_night (stay-date-effective macro group).

    Shares use the SAME filtered population as the denominator for every segment, so
    share_of_room_nights and share_of_revenue each sum to 1.0 across the returned segments.
    If macro_group is set, only segments with that effective macro_group are returned and
    shares are computed within that filtered population.

    GRAIN: room_nights = sum(number_of_spaces); total_revenue = sum(daily_total_revenue_before_tax).
    Returns: stay_month, macro_group, denominator{room_nights,total_revenue}, segments[...].
    """
    lo, hi = month_bounds(stay_month)
    params = {"lo": lo, "hi": hi}
    where_macro = ""
    if macro_group is not None:
        where_macro = "and effective_macro_group = %(macro_group)s"
        params["macro_group"] = macro_group
    rows = query(
        f"""
        select
          market_code,
          market_name,
          effective_macro_group                           as macro_group,
          coalesce(sum(number_of_spaces), 0)              as room_nights,
          coalesce(sum(daily_total_revenue_before_tax),0) as total_revenue
        from public.vw_segment_stay_night
        where stay_date >= %(lo)s and stay_date < %(hi)s
        {where_macro}
        group by market_code, market_name, effective_macro_group
        order by total_revenue desc
        """,
        params,
    )
    total_rn = sum(int(r["room_nights"]) for r in rows)
    total_rev = sum(_num(r["total_revenue"]) for r in rows)
    segments = []
    for r in rows:
        rn, rev = int(r["room_nights"]), _num(r["total_revenue"])
        segments.append(
            {
                "market_code": r["market_code"],
                "market_name": r["market_name"],
                "macro_group": r["macro_group"],
                "room_nights": rn,
                "total_revenue": rev,
                "share_of_room_nights": (rn / total_rn) if total_rn else 0.0,
                "share_of_revenue": (rev / total_rev) if total_rev else 0.0,
            }
        )
    return {
        "stay_month": stay_month,
        "macro_group": macro_group,
        "denominator": {"room_nights": total_rn, "total_revenue": total_rev},
        "segments": segments,
    }


# --------------------------------------------------------------------------- #
# 3. Pickup / pace
# --------------------------------------------------------------------------- #
def get_pickup_delta(booking_window_days: int, future_stay_from: str) -> dict:
    """Booking pace / pickup for future stays — uses create_datetime (booking date), NOT stay_date.

    The booking window is [start_of_day_london(today - booking_window_days), now], converted
    to UTC. Only stays with stay_date >= future_stay_from are counted. Universe is
    vw_stay_night_base (Posted, non-cancelled).

    GRAIN: new_reservations = count(distinct reservation_id) created in the window;
    new_room_nights = sum(number_of_spaces); new_total_revenue sums daily_total_revenue_before_tax.
    Returns: booking_window_days, future_stay_from, window_start_utc, window_end_utc,
    new_reservations, new_room_nights, new_total_revenue, by_segment[...].
    """
    # Effective "now" = when the book was captured (latest booking timestamp), so pickup
    # windows stay correct for a static dataset even as wall-clock time drifts past the scrape.
    captured = query_one("select max(create_datetime) as now from public.vw_stay_night_base")
    now_utc = captured.get("now") or datetime.now(UTC)
    today_london = now_utc.astimezone(LONDON).date()
    start_date = today_london - timedelta(days=booking_window_days)
    window_start = datetime.combine(start_date, time.min, tzinfo=LONDON).astimezone(UTC)
    params = {"win_start": window_start, "win_end": now_utc, "future_from": future_stay_from}

    totals = query_one(
        """
        select
          count(distinct reservation_id)                  as new_reservations,
          coalesce(sum(number_of_spaces), 0)              as new_room_nights,
          coalesce(sum(daily_total_revenue_before_tax),0) as new_total_revenue
        from public.vw_stay_night_base
        where create_datetime >= %(win_start)s and create_datetime <= %(win_end)s
          and stay_date >= %(future_from)s
        """,
        params,
    )
    by_segment = query(
        """
        select
          market_code,
          coalesce(sum(daily_total_revenue_before_tax),0) as total_revenue,
          coalesce(sum(number_of_spaces), 0)              as room_nights,
          count(distinct reservation_id)                  as reservations
        from public.vw_stay_night_base
        where create_datetime >= %(win_start)s and create_datetime <= %(win_end)s
          and stay_date >= %(future_from)s
        group by market_code
        order by total_revenue desc
        limit 5
        """,
        params,
    )
    return {
        "booking_window_days": booking_window_days,
        "future_stay_from": future_stay_from,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc": now_utc.isoformat(),
        "new_reservations": int(totals["new_reservations"]),
        "new_room_nights": int(totals["new_room_nights"]),
        "new_total_revenue": _num(totals["new_total_revenue"]),
        "by_segment": [
            {
                "market_code": r["market_code"],
                "total_revenue": _num(r["total_revenue"]),
                "room_nights": int(r["room_nights"]),
                "reservations": int(r["reservations"]),
            }
            for r in by_segment
        ],
    }


# --------------------------------------------------------------------------- #
# 4. As-of (point-in-time) OTB  — HUMAN-GATED (HITL) in the agent
# --------------------------------------------------------------------------- #
def get_as_of_otb(stay_month: str, as_of_utc: str) -> dict:
    """Point-in-time on-the-books for a stay month, as the book stood at as_of_utc (ISO-8601).

    Includes a stay row when ALL hold:
      - create_datetime <= as_of_utc                                  (already booked then)
      - reservation_status <> 'Cancelled' OR cancellation_datetime > as_of_utc (not yet cancelled)
      - financial_status = 'Posted'                                   (provisional excluded)

    This is an EXPENSIVE point-in-time rebuild; the agent gates it behind human approval.
    GRAIN: row_count = stay-date rows; reservation_count = distinct reservation_id;
    room_nights = sum(number_of_spaces). Same shape as get_otb_summary plus as_of_utc.
    """
    lo, hi = month_bounds(stay_month)
    as_of_dt = datetime.fromisoformat(as_of_utc.replace("Z", "+00:00"))
    row = query_one(
        """
        select
          count(*)                                       as row_count,
          count(distinct reservation_id)                 as reservation_count,
          coalesce(sum(number_of_spaces), 0)             as room_nights,
          coalesce(sum(daily_room_revenue_before_tax),0) as room_revenue,
          coalesce(sum(daily_total_revenue_before_tax),0) as total_revenue
        from public.vw_stay_night_posted
        where stay_date >= %(lo)s and stay_date < %(hi)s
          and create_datetime <= %(as_of)s
          and (reservation_status <> 'Cancelled' or cancellation_datetime > %(as_of)s)
        """,
        {"lo": lo, "hi": hi, "as_of": as_of_dt},
    )
    return {
        "stay_month": stay_month,
        "as_of_utc": as_of_utc,
        "row_count": int(row["row_count"]),
        "reservation_count": int(row["reservation_count"]),
        "room_nights": int(row["room_nights"]),
        "room_revenue": _num(row["room_revenue"]),
        "total_revenue": _num(row["total_revenue"]),
    }


# --------------------------------------------------------------------------- #
# 5. Block vs transient mix
# --------------------------------------------------------------------------- #
def get_block_vs_transient_mix(stay_month: str) -> dict:
    """Block vs transient mix for a stay month (vw_stay_night_base).

    Block = is_block true; transient = is_block false. block + transient room nights
    reconcile to the month's get_otb_summary room_nights.

    GRAIN: room_nights = sum(number_of_spaces); revenue = sum(daily_total_revenue_before_tax).
    Returns: block/transient room_nights & total_revenue, block_share_of_room_nights,
    block_share_of_revenue, top_companies (<=3 by revenue; null company -> 'Transient'),
    top3_company_revenue_share (0-1 of month total revenue).
    """
    lo, hi = month_bounds(stay_month)
    params = {"lo": lo, "hi": hi}
    bt = query(
        """
        select is_block,
          coalesce(sum(number_of_spaces), 0)              as room_nights,
          coalesce(sum(daily_total_revenue_before_tax),0) as total_revenue
        from public.vw_stay_night_base
        where stay_date >= %(lo)s and stay_date < %(hi)s
        group by is_block
        """,
        params,
    )
    block_rn = transient_rn = 0
    block_rev = transient_rev = 0.0
    for r in bt:
        if r["is_block"]:
            block_rn, block_rev = int(r["room_nights"]), _num(r["total_revenue"])
        else:
            transient_rn, transient_rev = int(r["room_nights"]), _num(r["total_revenue"])
    total_rn = block_rn + transient_rn
    total_rev = block_rev + transient_rev

    companies = query(
        """
        select coalesce(company_name, 'Transient')        as company,
          coalesce(sum(daily_total_revenue_before_tax),0) as total_revenue
        from public.vw_stay_night_base
        where stay_date >= %(lo)s and stay_date < %(hi)s
        group by coalesce(company_name, 'Transient')
        order by total_revenue desc
        limit 3
        """,
        params,
    )
    top_companies = [
        {"company_name": r["company"], "total_revenue": _num(r["total_revenue"])} for r in companies
    ]
    top3_rev = sum(c["total_revenue"] for c in top_companies)
    return {
        "stay_month": stay_month,
        "block_room_nights": block_rn,
        "transient_room_nights": transient_rn,
        "block_total_revenue": block_rev,
        "transient_total_revenue": transient_rev,
        "block_share_of_room_nights": (block_rn / total_rn) if total_rn else 0.0,
        "block_share_of_revenue": (block_rev / total_rev) if total_rev else 0.0,
        "top_companies": top_companies,
        "top3_company_revenue_share": (top3_rev / total_rev) if total_rev else 0.0,
    }


# Convenient registry for the agent layer (Phase 3).
ALL_TOOLS = [
    get_otb_summary,
    get_segment_mix,
    get_pickup_delta,
    get_as_of_otb,
    get_block_vs_transient_mix,
]
