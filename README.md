# Revenue Manager Agent — build-challenge solution

An AI **Revenue Manager for a hotel GM**, built on **LangChain Deep Agents** over reservation
data this repo ingests itself. Solution to the `otel-build-challenge` brief.

- **ETL** scrapes the client-rendered data site (Playwright) → loads Postgres → proof matches `/verify`.
- **Tool layer**: five tested tools over semantic views (no raw SQL exposed to the model).
- **Deep Agent**: skills (judgment), a segment subagent, planning, memory, and HITL on `get_as_of_otb`.
- **Serving**: one FastAPI service — basic auth, `/health`, and a streaming chat UI.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and [ATTESTATION.md](ATTESTATION.md)
for the Phase-0 comprehension answers.

## Layout

```
etl/        scrape.py · transform.py · load.py · run_etl.py  (+ SCRAPE_MANIFEST.json, LOAD_PROOF.json)
sql/        views.sql  (vw_stay_night_base, vw_stay_night_posted, vw_segment_stay_night)
tools/      db.py · metrics.py (5 tools) · METRIC_DEFINITIONS.md
skills/     CHALLENGE_SKILL.md (otel-rm-v2) + 7 SKILL.md (3 judgment)
agent/      graph.py (create_deep_agent) · prompts.py · server.py (FastAPI)
tests/      test_etl.py(4) · test_tools.py(12) · test_skills.py(7) · test_agent.py(7) = 30
scripts/    compute_load_fingerprint.py · smoke_agent.py
```

## Run it locally

```bash
# 0. Python 3.11+ required (Deep Agents). Build the venv:
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium
cp .env.example .env          # then fill in the keys (see below)

# 1. Database
docker compose up -d --wait                                   # local Postgres + schema
docker compose exec -T postgres psql -U hackathon -d hotel_hackathon < sql/views.sql

# 2. ETL (scrape -> load -> proofs), then reconcile with /verify
.venv/bin/python -m etl.run_etl
.venv/bin/python scripts/compute_load_fingerprint.py --manifest etl/SCRAPE_MANIFEST.json --output etl/LOAD_PROOF.json

# 3. Tests (all 30)
.venv/bin/pytest

# 4. Talk to the agent (needs an LLM key, see below)
.venv/bin/python -m scripts.smoke_agent "What's driving September 2026?"
.venv/bin/uvicorn agent.server:app --port 8000               # then open http://localhost:8000
```

## LLM provider (`.env`)

Set `LLM_PROVIDER` and the matching key. **Gemini is recommended** — Groq's free tier (~12K
tokens/min) is too small for a full deep-agent request (~12.5K tokens).

| Provider | `.env` | Free? |
|----------|--------|-------|
| **Google Gemini** (recommended) | `LLM_PROVIDER=google` · `GOOGLE_API_KEY=...` ([aistudio.google.com](https://aistudio.google.com/apikey)) · `GOOGLE_MODEL=gemini-2.5-flash` | yes, generous TPM |
| Groq | `LLM_PROVIDER=groq` · `GROQ_API_KEY=...` · `GROQ_MODEL=llama-3.3-70b-versatile` | free tier too tight; use dev tier |

## Deploy (Phase 4)

**Recommended — one service + hosted DB:**

1. **DB:** create a free **Neon** Postgres. Apply `schema.sql` then `sql/views.sql`. Run the ETL
   against it (`DATABASE_URL=<neon-url> .venv/bin/python -m etl.run_etl`) so the hosted DB is loaded.
2. **Service:** deploy this repo to **Render/Railway** (free) with start command
   `uvicorn agent.server:app --host 0.0.0.0 --port $PORT`. Set env: `DATABASE_URL` (Neon),
   `LLM_PROVIDER` + key, `BASIC_AUTH_USER`, `BASIC_AUTH_PASSWORD`.
3. **Verify:** `GET /health` returns `db_fingerprint`, `dataset_revision`, `row_hash`,
   `financial_status_posted_only_rows` matching `etl/LOAD_PROOF.json`. The chat UI streams tool +
   skill calls; `get_as_of_otb` prompts for approval.
4. **Submit** per `SUBMISSION.md`: live URL + basic-auth creds (privately) + repo link.

**Alternative — LangGraph + Agent Chat UI:** `langgraph.json` exposes the graph
(`make_graph`) and merges `agent/server.py` for `/health`; point the Agent Chat UI at the
LangGraph server.

> Secrets live only in `.env` (git-ignored) / the host's env — never committed.
