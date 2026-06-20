---
name: otb-summary
description: >
  Use when the GM asks what business is on the books for a month — "what revenue is on the
  books for July?", "how many room nights in September?", "ADR by month". Routes to
  get_otb_summary and reads it with the correct grain and default OTB filters.
---

# On-the-books (OTB) summary

When the GM asks what is on the books for a month, call
**get_otb_summary(stay_month="YYYY-MM")**. The default universe is Posted + non-cancelled.

Read the result with grain in mind:

- `reservation_count` = bookings (distinct reservation_id).
- `row_count` = stay-date rows — **not** bookings.
- `room_nights` = rooms × nights (`sum(number_of_spaces)`).
- `room_revenue` (room only) ≤ `total_revenue` (includes packages/extras).
- ADR (when asked) = `room_revenue / room_nights`.

Only pass `exclude_cancelled=False` if the GM explicitly wants cancelled business included.
Answer in plain English: lead with the headline (e.g. revenue and room nights), then the
composition, then any caveat (e.g. "Posted, non-cancelled").
