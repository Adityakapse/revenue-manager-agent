# ATTESTATION.md (Phase 0)

Comprehension attestation for the Revenue Manager Agent build challenge.

---

## Candidate

- Name: Aditya Kapse
- Repository URL: https://github.com/Adityakapse/revenue-manager-agent
- Date: 2026-06-21

---

## Comprehension prompts

### 1. Fact-table grain

In one sentence, what is the grain of `reservations_hackathon`?

> One row per **reservation × stay_date** (one night of one reservation): a 3-night booking
> produces 3 rows, all sharing the same `reservation_id`, so counting rows is not the same as
> counting reservations.

### 2. Revenue columns

Name the two revenue columns and when to use each.

> `daily_room_revenue_before_tax` — room-only revenue for that stay night; use it for
> room-revenue and ADR questions ("revenue on the books", "ADR by room type").
> `daily_total_revenue_before_tax` — total revenue including non-room components
> (packages/breakfast); use it for broader "total revenue" questions. So
> `room_revenue <= total_revenue` for the same scope.

### 3. Row vs reservation

Give one example question where counting rows would be wrong.

> "How many reservations do we have arriving in July?" — counting rows over-counts, because every
> multi-night reservation contributes several stay-date rows. The correct measure is
> `count(distinct reservation_id)`. (Counting rows answers "room-nights / stay-nights", not "bookings".)

### 4. Schema fields

Is there an `otel_challenge_token` column in the official schema? If so, what is it used for?

> No. There is **no `otel_challenge_token` column** anywhere in `schema.sql`. The
> `reservations_hackathon` columns are: `reservation_stay_id`, `reservation_id`, `arrival_date`,
> `departure_date`, `stay_date`, `property_date`, `reservation_status`, `financial_status`,
> `create_datetime`, `cancellation_datetime`, `guest_country`, `is_block`, `is_walk_in`,
> `number_of_spaces`, `space_type`, `market_code`, `channel_code`, `source_name`, `rate_plan_code`,
> `daily_room_revenue_before_tax`, `daily_total_revenue_before_tax`, `nights`, `adr_room`,
> `lead_time`, `company_name`, `travel_agent_name`. This prompt is a comprehension trap — the
> honest answer is that no such column exists.

### 5. Default OTB filters

Which `reservation_status` and `financial_status` values are excluded from default OTB?

> Default on-the-books excludes `reservation_status = 'Cancelled'` **and**
> `financial_status = 'Provisional'`. So the default universe is **Posted, non-cancelled** rows —
> exactly what `vw_stay_night_base` encodes. We only relax these when the question explicitly asks
> about cancellations or tentative/provisional business.

### 6. Stay date vs property date

When can `property_date` differ from `stay_date`, and which field drives monthly OTB?

> `property_date` is the hotel business date attributed to a stay row; it usually equals `stay_date`
> but can differ on night-boundary / night-audit rows (Appendix B). Monthly OTB and segment-mix-by-month
> are driven by **`stay_date`**, not `property_date`.

### 7. Point-in-time OTB

How does `as_of_utc` change which cancelled rows are included in `get_as_of_otb`?

> `as_of_utc` is "what did the book look like at this moment in the past?". A reservation that was
> later cancelled was still on the books before it was cancelled, so a cancelled row is **included**
> when `cancellation_datetime > as_of_utc` (not yet cancelled at that time) and **excluded** when
> `cancellation_datetime <= as_of_utc` (already cancelled). We also only include rows whose
> `create_datetime <= as_of_utc` (already booked), and keep `financial_status = 'Posted'`.

### 8. Block vs transient

How does `is_block` affect a "group vs transient mix" question?

> `is_block` is the group/block flag. "Group" (block) business = rows where `is_block = true`;
> "transient" = the individual, non-block rows (`is_block = false`). A group-vs-transient mix question
> splits room-nights/revenue by that flag; `company_name` is typically populated on block rows and is
> used to find the largest groups.

### 9. List pagination

How many reservations does the data site show per list page?

> **100 reservations per list page** at `/reservations`.

### 10. Pagination completeness

How will you prove you did not miss the last list page during ETL?

> Three independent checks: (a) keep paging until a page returns fewer than 100 rows / the next page is
> empty; (b) reconcile `count(distinct reservation_id)` in the DB against `total_reservations` on
> `/verify` for the same anchor date; (c) commit `reservation_ids_sha256` (SHA-256 of the sorted
> reservation_id list) in `SCRAPE_MANIFEST.json` and confirm it matches what
> `compute_load_fingerprint.py` computes from the loaded DB.

### 11. Tool grain

For `get_otb_summary`, what is the difference between `row_count` and `reservation_count`?

> `row_count` = number of stay-date rows in scope (reservation × stay_date grain).
> `reservation_count` = `count(distinct reservation_id)` in the same scope. Because multi-night
> reservations span multiple rows, `row_count >= reservation_count` (and is usually strictly greater).
> They answer different questions: "how many stay-nights are booked" vs "how many bookings".

### 12. Human-in-the-loop

Why must `get_as_of_otb` be gated behind approval, and what goes wrong if it is not?

> `get_as_of_otb` is an expensive point-in-time rebuild: it re-derives the entire book as it stood at
> an arbitrary past timestamp by replaying `create_datetime` and `cancellation_datetime`. Gating it
> behind a human approval interrupt means a person confirms the `as_of_utc` and intent before a heavy
> recomputation runs. Without the gate, the agent could fire expensive as-of rebuilds speculatively or
> repeatedly, burn resources/quota, and quietly present a point-in-time number the GM never asked to
> reconstruct (easy to misread as current OTB).

### 13. Skill vs tool

Name one revenue-manager question that should load a **skill** but call **`get_segment_mix`**, not raw SQL.

> "Are we too dependent on OTA?" loads an **OTA-dependency skill** (which carries the judgment:
> the concentration threshold and the recommended action), but the actual numbers come from calling
> **`get_segment_mix`** to read OTA `share_of_revenue` — never hand-written SQL. The skill supplies
> interpretation; the tested tool supplies trustworthy figures.

---

## ETL design (one line)

Describe pagination strategy + idempotency approach + **anchor date** you will
scrape against (must match `/verify` on load day).

> Playwright drives a headless browser through `/reservations` 100-at-a-time (paging until a short/empty
> page) and drills into each `/reservations/<id>` detail page for the per-night rows and detail-only
> fields; the load is **idempotent** via upsert on the `(reservation_id, stay_date)` unique key (or
> truncate-and-reload), appending one `load_manifest` row per run; the **anchor date** is today's date,
> scraped and reconciled against `/verify` on the same calendar day.
