---
name: segment-mix
description: >
  Use for "what's driving <month>?", segment/market mix, and "how much is corporate / leisure /
  group / retail?". Routes to get_segment_mix using the stay-date-effective macro group.
---

# Segment mix — what's driving the month

For "what's driving July?", "which segments are biggest?", "what share is corporate?" call
**get_segment_mix(stay_month="YYYY-MM")**, optionally with `macro_group` to focus
(e.g. "Retail", "Corporate", "Leisure Group", "MICE").

Interpretation:

- `share_of_revenue` and `share_of_room_nights` are over the same scope and sum to 1.0.
- Use the **effective** `macro_group` the tool returns — it is stay-date-aware (e.g. PROM is
  "Leisure Group" for 2026 stays even though the static lookup once said Retail). Never use a
  static macro group.
- A segment "driving" the month has a high `share_of_revenue`. If a segment's revenue share is
  higher than its room-night share, it is pulling rate up; if lower, it is discounting.

Brief the GM like a morning stand-up: name the top 2-3 drivers with their shares, then say
whether the mix looks healthy or risky.
