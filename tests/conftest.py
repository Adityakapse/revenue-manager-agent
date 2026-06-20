"""Shared pytest fixtures: a session-scoped Postgres connection to the loaded DB."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://hackathon:hackathon@localhost:5432/hotel_hackathon"
)


@pytest.fixture(scope="session")
def conn():
    """One read-only connection for the whole test session."""
    with psycopg.connect(DB_URL) as connection:
        yield connection


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT
