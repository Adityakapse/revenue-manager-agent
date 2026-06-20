---
name: point-in-time-otb
description: >
  Use for as-of / point-in-time questions — "what did the book look like on <date>?",
  "how does today compare to 60 days ago?", pace since a past date. Routes to get_as_of_otb,
  which is gated behind human approval.
---

# Point-in-time (as-of) OTB

When the GM asks what the book looked like at a past moment — "where were we on 1 May for
September?", "how much have we picked up since then?" — call
**get_as_of_otb(stay_month="YYYY-MM", as_of_utc="YYYY-MM-DDTHH:MM:SSZ")**.

This reconstructs the book as it stood at `as_of_utc`: a reservation is included only if it was
created on or before that time and had not yet been cancelled then; Posted only. It is an
**expensive point-in-time rebuild and is gated behind human approval** — confirm the as-of
timestamp with the GM before running it, and state that timestamp in your answer.

Use it to compute pace: current OTB minus the as-of OTB tells you what has been booked since.
Do not use it as a substitute for current OTB (use get_otb_summary for "now").
