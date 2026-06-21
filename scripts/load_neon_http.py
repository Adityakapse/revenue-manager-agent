"""
Load a Neon database over its HTTPS SQL endpoint (port 443) instead of Postgres :5432.

Useful when :5432 egress is blocked (agent sandboxes, university/corporate networks). Applies
schema + views, loads the cached dataset, writes a load_manifest row, and reconciles the row
fingerprint with etl/LOAD_PROOF.json.

    NEON_DATABASE_URL="postgresql://...neon.../neondb?sslmode=require" \
        .venv/bin/python -m scripts.load_neon_http
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from etl.load import _FACT_COLUMNS
from etl.run_etl import CACHE_PATH
from etl.scrape import BASE
from etl.transform import transform_all

ROOT = Path(__file__).resolve().parents[1]
CONN = os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
HOST = urlparse(CONN).hostname or ""


def _default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"not serializable: {type(o)}")


def run(sql: str, params: list | None = None) -> list[dict]:
    body = json.dumps({"query": sql, "params": params or []}, default=_default).encode()
    req = urllib.request.Request(
        f"https://{HOST}/sql", method="POST", data=body,
        headers={"Content-Type": "application/json", "Neon-Connection-String": CONN},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()).get("rows", [])


def insert(table: str, columns: list[str], rows: list[dict], chunk: int = 100) -> None:
    for start in range(0, len(rows), chunk):
        batch = rows[start:start + chunk]
        n = len(columns)
        values, params = [], []
        for i, row in enumerate(batch):
            values.append("(" + ",".join(f"${i * n + j + 1}" for j in range(n)) + ")")
            params.extend(row[c] for c in columns)
        run(f"insert into public.{table} ({','.join(columns)}) values {','.join(values)}", params)


def main() -> None:
    if not CONN or not HOST:
        raise SystemExit("Set NEON_DATABASE_URL (or DATABASE_URL) to the Neon connection string.")

    # 1) schema + views (one statement per HTTP call)
    for f in ("schema.sql", "sql/views.sql"):
        for stmt in (ROOT / f).read_text(encoding="utf-8").split(";"):
            if stmt.strip():
                run(stmt)
        print(f"  applied {f}")

    # 2) transform the cached dataset
    scraped = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    t = transform_all(scraped)
    ref = t["reference"]
    print(f"  prepared {len(t['fact_rows'])} fact rows (anchor {scraped['anchor_date']})")

    # 3) idempotent load (FK parents first, then facts)
    run("""truncate table public.reservations_hackathon, public.market_macro_group_history,
           public.room_type_lookup, public.rate_plan_lookup, public.market_code_lookup,
           public.channel_code_lookup, public.load_manifest restart identity cascade""")
    insert("room_type_lookup", ["space_type", "room_class", "display_name", "number_of_rooms"], ref["room_types"])
    insert("rate_plan_lookup", ["rate_plan_code", "plan_family", "is_commissionable"], ref["rate_plans"])
    insert("market_code_lookup", ["market_code", "market_name", "macro_group", "description"], ref["markets"])
    insert("channel_code_lookup", ["channel_code", "channel_name", "channel_group"], ref["channels"])
    insert("market_macro_group_history", ["market_code", "valid_from", "valid_to", "macro_group"], ref["macro_history"])
    insert("reservations_hackathon", _FACT_COLUMNS, t["fact_rows"])

    # 4) fingerprint (must match LOAD_PROOF) + manifest row
    rows = run("""select reservation_id, stay_date::text as sd, financial_status as fs
                  from public.reservations_hackathon
                  order by reservation_id, stay_date, financial_status""")
    pair = hashlib.sha256(
        "\n".join(f"{r['reservation_id']}|{r['sd']}|{r['fs']}" for r in rows).encode()
    ).hexdigest()
    run("insert into public.load_manifest (dataset_revision, scraped_at, source_url, row_hash) "
        "values ($1,$2,$3,$4)",
        [scraped["dataset_revision"], datetime.now(timezone.utc).isoformat(), f"{BASE}/reservations", pair])

    counts = run("select count(*) c, count(distinct reservation_id) r from public.reservations_hackathon")[0]
    proof = json.loads((ROOT / "etl/LOAD_PROOF.json").read_text())
    print(f"  loaded {counts['c']} rows / {counts['r']} reservations")
    print(f"  row_hash: {pair}")
    print(f"\n  MATCHES etl/LOAD_PROOF.json: {pair == proof['reservation_stay_status_sha256']}")


if __name__ == "__main__":
    main()
