"""
Deep Agent wiring for the Revenue Manager.

A single create_deep_agent(...) call assembled from deliberate building blocks:
  - model        : Groq (free) chat model
  - tools        : the five tested metric tools (no run_sql)
  - skills       : the on-demand revenue-manager playbook (progressive disclosure)
  - subagents    : a focused segment/concentration analyst (context isolation)
  - interrupt_on : human approval gate on the expensive get_as_of_otb rebuild (HITL)
  - backend      : virtual filesystem rooted at the repo (so skills are readable)
  - checkpointer + store : durable multi-turn memory (and required for HITL interrupts)
Planning (write_todos) comes built in with the Deep Agents harness.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

from deepagents import SubAgent, create_deep_agent  # noqa: E402
from deepagents.backends import FilesystemBackend  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.store.memory import InMemoryStore  # noqa: E402

from agent.prompts import RM_PERSONA, SEGMENT_SUBAGENT_PROMPT  # noqa: E402
from tools.metrics import (  # noqa: E402
    ALL_TOOLS,
    get_block_vs_transient_mix,
    get_segment_mix,
)

SKILLS_DIR = REPO_ROOT / "skills"
# Expensive point-in-time rebuilds gated behind human approval.
HUMAN_GATED_TOOLS = ["get_as_of_otb"]


def anchor_date() -> str | None:
    """The dataset's 'today' (from the scrape manifest). The book is forward-looking from here."""
    try:
        return json.loads((REPO_ROOT / "etl" / "SCRAPE_MANIFEST.json").read_text())["anchor_date"]
    except Exception:
        return None


def build_system_prompt() -> str:
    """RM persona + a DATE CONTEXT block so the model resolves relative dates correctly.

    LLMs have no clock — without this, 'this month' gets guessed (e.g. a stale 2023 date) and
    lands on an empty period. We pin 'today' to the dataset anchor and tell it the book is
    forward-looking from there.
    """
    anchor = anchor_date()
    if not anchor:
        return RM_PERSONA
    year, month = anchor[:4], anchor[5:7]
    return (
        RM_PERSONA
        + f"""

DATE CONTEXT (read before choosing any stay_month):
- TODAY for this hotel's book is {anchor}. Treat {anchor} as "today" / "now".
- The book is FORWARD-LOOKING from {anchor}: on-the-books business runs {year}-{month} onward
  (into the following months), with prior-year rows only for same-time-last-year comparisons.
- Resolve relative dates against {anchor}: "this month" = {year}-{month};
  "next month" = the month after; "recently" / "last N days" = booking activity in the N days
  before {anchor}. Do NOT assume the calendar year is anything other than {year}.
- If a tool returns zero/empty, you almost certainly picked a period with no business (usually the
  wrong month). Re-check the month against {anchor} and retry before raising any alarm — an empty
  result is NOT evidence of a system fault."""
    )


def default_model():
    """Build the chat model from env (temperature 0 for stable tool-calling).

    LLM_PROVIDER selects the backend:
      - 'google' / 'gemini' : ChatGoogleGenerativeAI, GOOGLE_MODEL (generous free TPM —
                              recommended; a full deep-agent request comfortably fits).
      - 'groq' (default)    : ChatGroq, GROQ_MODEL (free tier capped at ~12K TPM, which is
                              too tight for the full agent — use Groq dev tier if you keep it).
    """
    provider = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
    if provider in ("google", "gemini", "google_genai"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=os.environ.get("GOOGLE_MODEL", "gemini-2.5-flash"),
            temperature=0,
        )
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0,
    )


def segment_subagent() -> SubAgent:
    """A focused analyst that ONLY sees the two segment/concentration tools — context isolation."""
    return {
        "name": "segment-analyst",
        "description": (
            "Focused analyst for segment/market mix and group/block concentration. Delegate "
            "'what's driving the month', channel/segment mix, OTA dependency, and group "
            "concentration questions here."
        ),
        "system_prompt": SEGMENT_SUBAGENT_PROMPT,
        "tools": [get_segment_mix, get_block_vs_transient_mix],
        "skills": [str(SKILLS_DIR)],
    }


_DEFAULT = object()  # sentinel: "use in-memory persistence" vs explicit None


def build_agent(checkpointer=_DEFAULT, store=_DEFAULT, model=None):
    """Construct the Deep Agent.

    Defaults to in-memory persistence (good for local runs + tests). Pass
    checkpointer=None / store=None to let a host (LangGraph platform) inject persistence,
    or pass a Postgres checkpointer/store for a self-managed deployment.
    """
    return create_deep_agent(
        model=model or default_model(),
        tools=ALL_TOOLS,
        system_prompt=build_system_prompt(),
        subagents=[segment_subagent()],
        skills=[str(SKILLS_DIR)],
        backend=FilesystemBackend(root_dir=str(REPO_ROOT), virtual_mode=False),
        interrupt_on={name: True for name in HUMAN_GATED_TOOLS},
        checkpointer=InMemorySaver() if checkpointer is _DEFAULT else checkpointer,
        store=InMemoryStore() if store is _DEFAULT else store,
    )


def make_graph():
    """Entry point for LangGraph deployment (referenced by langgraph.json).
    The platform supplies persistence, so we don't attach our own checkpointer/store."""
    return build_agent(checkpointer=None, store=None)


# Lazily-built singleton for the FastAPI server (one shared agent across requests).
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent
