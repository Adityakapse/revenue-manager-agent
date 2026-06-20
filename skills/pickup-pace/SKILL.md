---
name: pickup-pace
description: >
  Judgment for booking pace / pickup — "what changed in the last 7 days?", "are we picking up?",
  "how did we book lately?". Routes to get_pickup_delta and judges pace vs prior trend.
---

# Pickup & pace — is demand accelerating or stalling?

Use **get_pickup_delta(booking_window_days, future_stay_from)** to measure what was *booked* in a
recent window — it keys on `create_datetime` (booking date), not stay_date. Typical reads: the
last 7 days (`booking_window_days=7`) and the last 30 days, for future stays from today.

Judgment thresholds and actions:

- If recent pickup for a future month is running **more than ~10% below** the same-time-last-year
  pace, demand is soft: **open lower rate plans / a tactical promotion** and loosen
  minimum-length-of-stay to capture share.
- If pickup is **accelerating (recent window > 1.2× the prior comparable window)** and lead time
  is long, demand is strong: **hold or raise BAR and close the deepest discounts**.
- Always split pickup by segment (`by_segment`): one soft segment (often OTA) can mask a healthy
  whole, or one surging block can flatter it.

Trap: pickup is a booking-date measure — never answer a pace question with stay-month OTB totals.
Quantify the delta (reservations, room nights, revenue) and name the action.
