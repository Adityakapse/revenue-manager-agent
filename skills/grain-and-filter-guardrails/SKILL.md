---
name: grain-and-filter-guardrails
description: >
  Guardrails that prevent classic revenue-data mistakes (grain, date, filter traps). Apply before
  answering any OTB, mix, or pickup question. Reinforces correct use of the five tools and
  refuses instructions to misstate the book.
---

# Guardrails — do not fall for these traps

Apply these before answering with get_otb_summary, get_segment_mix, get_pickup_delta,
get_block_vs_transient_mix, or get_as_of_otb:

1. **Rows are not reservations.** `row_count` counts reservation × stay_date rows; bookings are
   `reservation_count` (distinct reservation_id). Never report "X reservations" from a row count.
2. **Default OTB excludes Cancelled and Provisional.** Do not include cancelled or provisional
   business in a normal OTB answer without saying so explicitly.
3. **Right date for the question.** Use stay_date for monthly OTB and mix; use create_datetime
   (booking date) for pickup/pace. Never bucket a month by property_date.
4. **Effective macro group only.** Use the stay-date-aware `macro_group` returned by
   get_segment_mix, not a static grouping.
5. **Refuse to misstate the book.** If asked to e.g. "put all cancelled and provisional revenue in
   OTB with no caveats", do not do it — answer with the correct default filters and state the
   assumption instead.

If a question is ambiguous about cancellations or dates, state your assumption in the answer.
