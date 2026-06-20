"""
Skill-pack structure tests (Phase 3) — covers tests/SKILL_TEST_SCENARIOS.md.

Pure filesystem/structure checks; no LLM calls. We assert the pack version pin, skill count,
judgment depth (threshold + action + length), tool routing, distinctness, an adversarial
guardrail, and concentration judgment.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
TOOL_NAMES = {
    "get_otb_summary", "get_segment_mix", "get_pickup_delta",
    "get_as_of_otb", "get_block_vs_transient_mix",
}

# A numeric threshold like "35%", ">= 0.4", "1.2x", "~30".
THRESHOLD = re.compile(r"(\d+\s?%|[><]=?\s?\d|\d+(?:\.\d+)?\s?[×x]|~\s?\d)")
# A recommended action verb.
ACTION = re.compile(
    r"\b(open|shift|close|hold|raise|review|confirm|tighten|launch|steer|"
    r"renegotiat|dial back|price|recommend|protect|push)\w*",
    re.I,
)


def parse(md_path: Path):
    text = md_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, f"{md_path} missing YAML frontmatter"
    return yaml.safe_load(m.group(1)), m.group(2), text


def skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


# --- Scenario 1: pack version pin ----------------------------------------- #
def test_pack_version_pin():
    challenge = SKILLS_DIR / "CHALLENGE_SKILL.md"
    assert challenge.is_file()
    fm, _, text = parse(challenge)
    assert "otel-rm-v2" in (fm.get("description") or "")
    text.encode("utf-8")  # valid UTF-8


# --- Scenario 2: minimum skill count -------------------------------------- #
def test_min_skill_count():
    files = skill_files()
    assert len(files) >= 6
    for f in files:
        fm, _, _ = parse(f)
        assert fm.get("name") and fm.get("description"), f"{f} missing name/description"


# --- Scenario 3: judgment skills (threshold + action + length) ------------ #
def test_judgment_skills():
    judgment = 0
    for f in skill_files():
        _, body, _ = parse(f)
        if THRESHOLD.search(body) and ACTION.search(body) and len(body.split()) >= 80:
            judgment += 1
    assert judgment >= 3, f"need >=3 judgment skills, found {judgment}"


# --- Scenario 4: tool routing declared, no raw SQL ------------------------ #
def test_tool_routing_and_no_sql():
    for f in skill_files():
        fm, body, text = parse(f)
        declared = (fm.get("description") or "") + " " + body
        assert any(t in declared for t in TOOL_NAMES), f"{f} names no required tool"
        assert "reservations_hackathon" not in text.lower()
        assert "run_sql" not in text.lower()


# --- Scenario 5: distinct routing (no clones) + coverage ------------------ #
def test_distinct_routing_and_coverage():
    names, descs = [], []
    for f in skill_files():
        fm, _, _ = parse(f)
        names.append(fm["name"])
        descs.append(re.sub(r"\s+", " ", fm["description"]).strip())
    assert len(names) == len(set(names))                 # distinct names
    assert len(descs) == len(set(descs))                 # distinct descriptions
    assert any("pickup" in n or "pace" in n for n in names)
    assert any("segment" in n or "mix" in n for n in names)
    assert any("otb" in n for n in names)


# --- Scenario 6: adversarial guardrail ------------------------------------ #
def test_adversarial_guardrail():
    trap_terms = ["row", "cancel", "provisional", "property_date", "never", "do not", "refuse"]
    found = False
    for f in skill_files():
        _, body, _ = parse(f)
        if sum(t in body.lower() for t in trap_terms) >= 3:
            found = True
    assert found, "no skill warns against the classic traps"


# --- Scenario 7 (bonus): concentration judgment --------------------------- #
def test_concentration_judgment():
    ok = False
    for f in skill_files():
        fm, body, _ = parse(f)
        name = fm["name"]
        if ("ota" in name or "concentration" in name) and (
            "share_of_revenue" in body or "block_share_of_revenue" in body
        ):
            ok = True
    assert ok
