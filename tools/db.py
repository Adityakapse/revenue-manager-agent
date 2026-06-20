"""
Database access for the tool layer.

Deliberately minimal and SAFE:
  - the agent/model never supplies SQL; only our own parameterized queries run here
  - every query is read-only against the semantic VIEWS (not the raw fact table)
  - results come back as plain dicts for easy JSON-able tool returns

This module is importable without starting any agent/server (brief Scenario 12).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

# Load DATABASE_URL from the repo .env if present (no-op when already set).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_DATABASE_URL = "postgresql://hackathon:hackathon@localhost:5432/hotel_hackathon"


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a read-only, parameterized query and return rows as dicts."""
    with psycopg.connect(get_database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()


def query_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a query expected to return a single row."""
    rows = query(sql, params)
    return rows[0] if rows else {}


def month_bounds(stay_month: str) -> tuple[date, date]:
    """
    Turn 'YYYY-MM' into a half-open [first_of_month, first_of_next_month) date range,
    so callers filter `stay_date >= lo AND stay_date < hi` (avoids end-of-month bugs).
    """
    year, month = (int(p) for p in stay_month.split("-"))
    lo = date(year, month, 1)
    hi = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return lo, hi


def _num(value: Any) -> float:
    """Coerce a possibly-Decimal/None DB value to a plain float for JSON returns."""
    return float(value) if value is not None else 0.0
