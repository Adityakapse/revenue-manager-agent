# Metric definitions

Single source of truth for what each number means. The tool layer (`tools/metrics.py`)
implements exactly these definitions and is tested in `tests/test_tools.py`.

## Counting grain — room nights vs stay rows vs reservations

The fact table `reservations_hackathon` has **one row per `reservation_id` × `stay_date`**.

| Metric | Definition | Why it differs |
|--------|------------|----------------|
| **stay rows** (`row_count`) | `count(*)` of stay-date rows in scope | a 3-night booking = 3 rows |
| **reservations** (`reservation_count`) | `count(distinct reservation_id)` | the number of actual bookings |
| **room nights** (`room_nights`) | `sum(number_of_spaces)` | rooms × nights (2 rooms × 3 nights = 6) |

So `room_nights ≥ reservation_count` and (with any multi-night booking) `row_count > reservation_count`.
Counting rows is **not** counting bookings.

## Revenue columns

- **`room_revenue`** = `sum(daily_room_revenue_before_tax)` — room only. Use for room-revenue / ADR questions.
- **`total_revenue`** = `sum(daily_total_revenue_before_tax)` — room + extras (packages/breakfast).
- Therefore `room_revenue ≤ total_revenue` for the same scope.

## Default OTB (on-the-books) filters

Default universe = **Posted, non-cancelled** (view `vw_stay_night_base`):

1. exclude `reservation_status = 'Cancelled'`
2. exclude `financial_status = 'Provisional'`

Relaxed only when asked: `get_otb_summary(exclude_cancelled=False)` adds cancelled rows
(still Posted); cancellation questions read cancelled rows explicitly.
**Anchor date:** the dataset is regenerated daily and forward-looking from *today*; counts
are reconciled against `/verify` on the scrape day (here 2026-06-15, revision `2026.06.12.2`).

## Which date drives which metric

- **`stay_date`** → monthly OTB, revenue-on-stay, segment/block mix by stay month.
- **`create_datetime`** (UTC) → pickup / booking pace ("what was booked recently").
- **`cancellation_datetime`** → point-in-time as-of OTB.
- **`property_date`** → hotel business date; only used when it differs from `stay_date`
  (tools filter months by `stay_date`, never `property_date`).

## Pickup window boundaries (Europe/London vs UTC)

`get_pickup_delta` defines the booking window as
`[ start_of_day_London(today − booking_window_days) , now ]`, converted to **UTC** before
comparing to `create_datetime` (which is stored in UTC). Booking pace is driven by
`create_datetime`, never `stay_date`.

## Effective vs static macro group

A market code's macro group can change over time (e.g. `PROM` was reclassified
Retail → Leisure Group effective 2025-06-01). The **effective** macro group is resolved by
joining `market_macro_group_history` on `stay_date ∈ [valid_from, valid_to)`
(view `vw_segment_stay_night.effective_macro_group`) — **not** the static
`market_code_lookup.macro_group`. Segment mix uses the effective value.
