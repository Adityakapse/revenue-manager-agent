---
name: ota-dependency
description: >
  Judgment for "are we too dependent on OTA?" and channel-mix / margin risk. Routes to
  get_segment_mix and reads the OTA segment's share_of_revenue to assess concentration.
---

# OTA dependency — concentration & margin risk

When the GM asks "are we too dependent on OTA?", call **get_segment_mix(stay_month="YYYY-MM")**
and read the OTA segment's **share_of_revenue** (and `share_of_room_nights`).

Judgment thresholds and actions:

- OTA `share_of_revenue` **above ~35%** of a month is a dependency flag: OTAs carry roughly
  15-25% commission, so a high OTA share erodes net ADR. **Shift demand to direct** (brand.com,
  loyalty / member rates), review rate parity, and dial back OTA availability *if* booking pace is
  healthy enough to backfill.
- OTA `share_of_revenue` **above ~50%** is a red flag — the property is renting its demand.
  **Launch a direct-booking push and renegotiate OTA terms** before raising public rates.
- OTA `share_of_revenue` **below ~20%** with soft occupancy: OTAs are a useful demand tap —
  **open a little more OTA inventory tactically**.

Compare OTA's revenue share to its room-night share: if revenue share is the lower of the two,
OTA is also discounting rate, compounding the margin hit. Quantify the £ at stake, not just the %.
