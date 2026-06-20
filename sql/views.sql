-- Semantic views for Phase 2. Required tools must query these views, not raw
-- reservations_hackathon. Default OTB universe = Posted + non-cancelled.

-- Default OTB grain: Posted AND non-cancelled. Used by get_otb_summary (default),
-- get_segment_mix, get_pickup_delta, get_block_vs_transient_mix.
create or replace view public.vw_stay_night_base as
select
  r.*
from public.reservations_hackathon r
where r.reservation_status <> 'Cancelled'
  and r.financial_status = 'Posted';

-- Posted but INCLUDING cancelled rows. Needed by:
--   * get_otb_summary(exclude_cancelled=False)  -> show cancelled business too
--   * get_as_of_otb                              -> a row cancelled AFTER as_of was
--     still on the books at as_of, so we must keep cancelled rows and filter by time.
-- Provisional stays excluded here too (default OTB excludes provisional regardless).
create or replace view public.vw_stay_night_posted as
select
  r.*
from public.reservations_hackathon r
where r.financial_status = 'Posted';

create or replace view public.vw_segment_stay_night as
select
  b.*,
  coalesce(h.macro_group, m.macro_group) as effective_macro_group,
  m.market_name
from public.vw_stay_night_base b
join public.market_code_lookup m on m.market_code = b.market_code
left join lateral (
  select h.macro_group
  from public.market_macro_group_history h
  where h.market_code = b.market_code
    and b.stay_date >= h.valid_from
    and (h.valid_to is null or b.stay_date < h.valid_to)
  order by h.valid_from desc
  limit 1
) h on true;
