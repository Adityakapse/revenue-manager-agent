---
name: group-block-concentration
description: >
  Judgment for "is our business concentrated in a few big bookings?" and group-vs-transient risk.
  Routes to get_block_vs_transient_mix and reads block_share_of_revenue + top companies.
---

# Group / block concentration risk

For "is business concentrated in a few large bookings?", "how much is group?", "which companies
drive revenue?" call **get_block_vs_transient_mix(stay_month="YYYY-MM")**.

Judgment thresholds and actions:

- If `top3_company_revenue_share` (looking past the 'Transient' bucket) is **above ~30%** of the
  month, the month is concentrated — one cancellation or block wash can swing the result.
  **Confirm block cutoff dates, attrition/wash clauses, and materialization** before protecting
  inventory or quoting new groups.
- If `block_share_of_revenue` is **above ~40%**, transient pricing power on peak dates is limited:
  **tighten group ceilings on high-demand dates and steer new group requests to need dates**.
- Low concentration (`top3_company_revenue_share` < ~15% and `block_share_of_revenue` < ~20%)
  means broad, resilient demand — **price transient with confidence**.

Trap: blocks inflate room nights without guaranteed materialization — never treat block OTB as
certain. Name the largest company and the £ exposure if that block washes.
