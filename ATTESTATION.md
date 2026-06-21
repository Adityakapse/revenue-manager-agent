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

> One row per reservation per stay date. A 3-night booking makes 3 rows that all share the same
> reservation_id, so counting rows is not the same as counting reservations.

### 2. Revenue columns

Name the two revenue columns and when to use each.

> daily_room_revenue_before_tax is the room-only revenue for that night. I use it for room
> revenue and ADR questions. daily_total_revenue_before_tax is the total including extras like
> packages and breakfast, so I use it for broader "total revenue" questions. Room revenue is
> always less than or equal to total revenue for the same scope.

### 3. Row vs reservation

Give one example question where counting rows would be wrong.

> "How many reservations arrive in July?" If you count rows you over-count, because every
> multi-night booking has several stay-date rows. The right answer is count(distinct
> reservation_id). Counting rows gives you stay-nights, not bookings.

### 4. Schema fields

Is there an `otel_challenge_token` column in the official schema? If so, what is it used for?

> No. There is no otel_challenge_token column in schema.sql. The reservations_hackathon columns
> are reservation_stay_id, reservation_id, arrival_date, departure_date, stay_date, property_date,
> reservation_status, financial_status, create_datetime, cancellation_datetime, guest_country,
> is_block, is_walk_in, number_of_spaces, space_type, market_code, channel_code, source_name,
> rate_plan_code, daily_room_revenue_before_tax, daily_total_revenue_before_tax, nights, adr_room,
> lead_time, company_name and travel_agent_name. The prompt looks like a trap, and the honest
> answer is that the column does not exist.

### 5. Default OTB filters

Which `reservation_status` and `financial_status` values are excluded from default OTB?

> Default on-the-books drops reservation_status = 'Cancelled' and financial_status = 'Provisional'.
> So the default is posted, non-cancelled rows, which is what the vw_stay_night_base view does. I
> only relax that when the question is specifically about cancellations or provisional business.

### 6. Stay date vs property date

When can `property_date` differ from `stay_date`, and which field drives monthly OTB?

> property_date is the hotel business date for a stay row. It usually equals stay_date but can
> differ on night-audit or boundary rows (Appendix B). Monthly OTB and segment mix by month use
> stay_date, not property_date.

### 7. Point-in-time OTB

How does `as_of_utc` change which cancelled rows are included in `get_as_of_otb`?

> as_of_utc means "what did the book look like at that moment in the past". A reservation that was
> cancelled later was still on the books before then, so a cancelled row is kept when its
> cancellation_datetime is after as_of_utc, and dropped when it is on or before as_of_utc. I also
> only count rows created on or before as_of_utc, and keep financial_status = 'Posted'.

### 8. Block vs transient

How does `is_block` affect a "group vs transient mix" question?

> is_block is the group flag. Group (block) business is the rows with is_block = true, and
> transient is the rest, where is_block = false. A group-vs-transient question splits room nights
> and revenue on that flag. company_name is usually filled in for blocks, which is how you find
> the biggest groups.

### 9. List pagination

How many reservations does the data site show per list page?

> 100 reservations per page on /reservations.

### 10. Pagination completeness

How will you prove you did not miss the last list page during ETL?

> Three checks. Keep paging until a page has fewer than 100 rows or the next page is empty.
> Reconcile count(distinct reservation_id) in the database against total_reservations on /verify
> for the same anchor date. And commit reservation_ids_sha256, the SHA-256 of the sorted
> reservation_id list, in SCRAPE_MANIFEST.json, then confirm it matches what
> compute_load_fingerprint.py reads back from the loaded database.

### 11. Tool grain

For `get_otb_summary`, what is the difference between `row_count` and `reservation_count`?

> row_count is the number of stay-date rows in scope (reservation per stay date). reservation_count
> is count(distinct reservation_id) for the same scope. Because multi-night bookings span several
> rows, row_count is at least reservation_count and usually larger. They answer different things:
> stay-nights booked versus number of bookings.

### 12. Human-in-the-loop

Why must `get_as_of_otb` be gated behind approval, and what goes wrong if it is not?

> get_as_of_otb is an expensive rebuild. It re-derives the whole book as of an arbitrary past time
> by replaying create_datetime and cancellation_datetime. Putting a human approval step in front
> means someone confirms the timestamp and the intent before that heavy query runs. Without it the
> agent could fire as-of rebuilds on its own, repeatedly, waste resources, and hand the GM a
> point-in-time number they never asked for, which is easy to mistake for current OTB.

### 13. Skill vs tool

Name one revenue-manager question that should load a **skill** but call **`get_segment_mix`**, not raw SQL.

> "Are we too dependent on OTA?" It should load the OTA-dependency skill, which holds the
> threshold and the recommended action, but read the actual numbers from get_segment_mix, looking
> at OTA's share_of_revenue. No hand-written SQL. The skill gives the judgment and the tool gives
> the numbers.

---

## ETL design (one line)

Describe pagination strategy + idempotency approach + **anchor date** you will
scrape against (must match `/verify` on load day).

> Playwright drives a headless browser through /reservations 100 at a time, paging until a short
> or empty page, and opens each /reservations/<id> detail page for the per-night rows and the
> detail-only fields. The load is idempotent (truncate-and-reload, or upsert on the
> (reservation_id, stay_date) key) and writes one load_manifest row per run. The anchor date is
> today's date, scraped and reconciled against /verify on the same day.
