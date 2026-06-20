# ARCHITECTURE — Revenue Manager Agent

One-page map of the build: ETL → semantic views → tested tool layer → Deep Agent (skills,
subagent, HITL, memory) → deployment.

## 1. ETL boundary (`etl/`)

- **Extract** (`scrape.py`): Playwright/Chromium drives the client-rendered data site, paginates
  the reservation list (**100/page**, clicking "Next →" until complete), drills into each
  `/reservations/<id>` detail page for booking fields + per-night stay rows, and reads the 5
  `/reference` lookup tabs. IDs are discovered from the page (not guessed), so planted edge-case
  records (`RES-EDGE-*`, `RES-ZEPHYR-*`) are captured.
- **Transform** (`transform.py`): types raw strings (dates, UTC timestamps, numerics, booleans),
  maps "—" → NULL, and enforces the **reservation × stay_date** grain (stamps booking fields onto
  each stay-night row).
- **Load** (`load.py`): idempotent truncate-and-reload (FK parents first), one `load_manifest` row
  per run whose `row_hash` equals the dataset fingerprint.
- **Verify**: `run_etl.py` writes `etl/SCRAPE_MANIFEST.json`; `scripts/compute_load_fingerprint.py`
  writes `etl/LOAD_PROOF.json`. Both reconcile with `/verify` (anchor 2026-06-15, revision
  `2026.06.12.2`): 254 reservations / 516 stay rows and a matching `reservation_stay_status_sha256`.

## 2. Database and views (Neon in prod; Docker locally)

Tools never touch the raw table. They read semantic views (`sql/views.sql`):

- `vw_stay_night_base` — default OTB universe (Posted, non-cancelled).
- `vw_stay_night_posted` — Posted incl. cancelled (for `exclude_cancelled=False` and as-of logic).
- `vw_segment_stay_night` — adds the **stay-date-effective** `macro_group` (history join; e.g. PROM
  → Leisure Group from 2025-06-01).

> One documented deviation: the data site's reservations use granular commercial rate codes that
> exceed the 8-row `rate_plan_lookup`, which the site itself does not FK-enforce. We keep
> `rate_plan_lookup` at the canonical 8 and relax that single FK (see `schema.sql`).

## 3. Tool layer (`tools/`)

Five tools (`metrics.py`), each with exact names, the grain in its docstring, parameterized SQL,
and **no free-form SQL parameter**. `db.py` gives read-only dict queries + month bounds.
Definitions live in `tools/METRIC_DEFINITIONS.md`. The model composes answers from these; it
cannot improvise SQL.

## 4. Deep Agents wiring (`agent/graph.py`)

| Building block | Our use |
|----------------|---------|
| Model | Groq `llama-3.3-70b-versatile` (free), temperature 0 |
| Tools | the five named tools — no `run_sql` |
| Skills | `skills/` (7 `SKILL.md`, progressive disclosure) |
| Subagent | **`segment-analyst`** — only `get_segment_mix` + `get_block_vs_transient_mix` (isolation) |
| Planning | built-in `write_todos` (decompose multi-part GM questions) |
| Memory / filesystem | `FilesystemBackend` + checkpointer + store (multi-turn) |
| Human-in-the-loop | `interrupt_on={"get_as_of_otb": True}` (expensive point-in-time rebuild) |
| System prompt | sharp revenue-manager persona (`prompts.py`) |

## 5. Skill → tool routing matrix

| Skill | Loads for | Primary tool(s) | Judgment? |
|-------|-----------|-----------------|-----------|
| `otb-summary` | "what's on the books for <month>?" | `get_otb_summary` | N |
| `segment-mix` | "what's driving <month>?", mix/share | `get_segment_mix` | light |
| `pickup-pace` | "what changed lately?", pace | `get_pickup_delta` | **Y** |
| `ota-dependency` | "too dependent on OTA?" | `get_segment_mix` | **Y** |
| `group-block-concentration` | "concentrated in big bookings?" | `get_block_vs_transient_mix` | **Y** |
| `point-in-time-otb` | "what did the book look like on <date>?" | `get_as_of_otb` (HITL) | N |
| `grain-and-filter-guardrails` | every answer (avoid traps) | all five | guardrail |

`skills/CHALLENGE_SKILL.md` pins pack version **`otel-rm-v2`**.

## 6. Agent & skill tests

- `tests/test_agent.py` (7): exactly the five tools (no `run_sql`); HITL middleware wired with
  `get_as_of_otb` as the interrupt target; segment subagent restricted to the two segment tools;
  planning present; recorded composite trace shows ≥2 tools; checkpointer configured; refusal policy.
- `tests/test_skills.py` (7): version pin, ≥6 skills, ≥3 judgment (threshold+action+≥80 words),
  tool routing & no raw SQL, distinct routing + coverage, adversarial guardrail, concentration judgment.
- All structural — no live LLM calls. Full suite: **30 passing** (ETL 4, tools 12, skills 7, agent 7).

## 7. Deployment topology

- **DB:** hosted Postgres (Neon), loaded once by the ETL.
- **Agent:** Deep Agent served on LangGraph; `agent/server.py` adds `GET /health` + HTTP basic auth.
- **UI:** Agent Chat UI (streams tool/skill calls; loading a skill is a `read_file` tool call).
- **`GET /health`** → `db_fingerprint` (= `reservation_stay_status_sha256`), `dataset_revision`,
  `row_hash` (= `load_manifest.row_hash`), `financial_status_posted_only_rows` (= LOAD_PROOF
  `posted_stay_rows`). API keys via env only — never committed.

## 8. Out of scope (deliberate)

No MCP servers (optional bonus); no daily ETL cron (anchor-day reproducibility is enough); UI is
function-first, not styled.
