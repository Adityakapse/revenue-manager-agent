"""
Agent structural tests (Phase 3) — covers tests/AGENT_TEST_SCENARIOS.md.

Graph introspection + a recorded trace fixture; NO live LLM calls. A dummy GROQ key lets us
construct the model object (we never invoke it here).
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("GROQ_API_KEY", "gsk_dummy_for_structural_tests")

from agent.graph import HUMAN_GATED_TOOLS, build_agent, segment_subagent  # noqa: E402
from tools.metrics import ALL_TOOLS  # noqa: E402

REQUIRED_TOOLS = {
    "get_otb_summary",
    "get_segment_mix",
    "get_pickup_delta",
    "get_as_of_otb",
    "get_block_vs_transient_mix",
}


@pytest.fixture(scope="module")
def agent():
    return build_agent()


def node_names(agent) -> set[str]:
    return set(agent.get_graph().nodes.keys())


# --- Scenario 1: tool surface is fixed (exactly the five, no run_sql) ------ #
def test_fixed_tool_surface():
    names = {t.__name__ for t in ALL_TOOLS}
    assert names == REQUIRED_TOOLS
    assert "run_sql" not in names
    for t in ALL_TOOLS:
        params = set(inspect.signature(t).parameters)
        assert not ({"sql", "query", "statement"} & params), f"{t.__name__} exposes raw SQL param"


# --- Scenario 2: get_as_of_otb is human-gated (HITL) ---------------------- #
def test_as_of_is_human_gated(agent):
    assert "get_as_of_otb" in HUMAN_GATED_TOOLS  # the interrupt target
    assert any("HumanInTheLoop" in n for n in node_names(agent))  # HITL middleware wired


# --- Scenario 3: segment work is isolated (subagent w/ only the 2 tools) --- #
def test_segment_work_isolated():
    sa = segment_subagent()
    assert sa["name"] == "segment-analyst"
    tool_names = {t.__name__ for t in sa["tools"]}
    assert tool_names == {"get_segment_mix", "get_block_vs_transient_mix"}
    assert "get_as_of_otb" not in tool_names  # isolation: no broad tool access


# --- Scenario 4: multi-tool decomposition --------------------------------- #
def test_multitool_decomposition(agent):
    # planning is enabled (lets the agent decompose multi-part questions before tool calls)
    assert any("Todo" in n for n in node_names(agent))
    # recorded trace: a composite question invoked >= 2 distinct (valid) tools
    trace = json.loads((Path(__file__).parent / "fixtures" / "composite_trace.json").read_text())
    called = {step["tool"] for step in trace["tool_calls"]}
    assert len(called) >= 2
    assert called <= REQUIRED_TOOLS


# --- Scenario 5: skills load on demand (not a monolithic prompt) ---------- #
def test_skills_loaded_on_demand(agent):
    assert any("Skill" in n for n in node_names(agent)), "SkillsMiddleware not wired"


# --- Scenario 6: memory / filesystem configured --------------------------- #
def test_memory_configured(agent):
    assert agent.checkpointer is not None  # multi-turn memory + HITL persistence


# --- Scenario 7 (bonus): refusal policy lives in a skill ------------------ #
def test_refusal_policy_present():
    guard = (
        (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "grain-and-filter-guardrails"
            / "SKILL.md"
        )
        .read_text()
        .lower()
    )
    assert "refuse" in guard and "provisional" in guard
