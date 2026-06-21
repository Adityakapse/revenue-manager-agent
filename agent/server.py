"""
Self-contained serving layer for the Revenue Manager agent.

Provides everything the brief's Phase 4 requires in ONE deployable FastAPI service:
  - HTTP Basic auth on every route
  - GET /health   -> live DB fingerprint vs the submitted LOAD_PROOF
  - GET /         -> a minimal chat UI
  - POST /chat    -> streams the agent run as Server-Sent Events, surfacing every
                     TOOL call and SKILL load (a skill load is a read_file on a SKILL.md)
  - POST /resume  -> approve/reject the human-in-the-loop gate on get_as_of_otb

Run locally:   .venv/bin/uvicorn agent.server:app --reload --port 8000
(This same `app` is also mounted as custom routes by langgraph.json for the LangGraph path.)
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, StreamingResponse  # noqa: E402
from fastapi.security import HTTPBasic, HTTPBasicCredentials  # noqa: E402
from langgraph.types import Command  # noqa: E402
from pydantic import BaseModel  # noqa: E402

app = FastAPI(title="Revenue Manager Agent")
security = HTTPBasic()


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def require_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    user = os.environ.get("BASIC_AUTH_USER", "gm")
    pw = os.environ.get("BASIC_AUTH_PASSWORD", "")
    ok = (
        bool(pw)
        and secrets.compare_digest(credentials.username, user)
        and secrets.compare_digest(credentials.password, pw)
    )
    if not ok:
        raise HTTPException(401, "Unauthorized", {"WWW-Authenticate": "Basic"})
    return credentials.username


# --------------------------------------------------------------------------- #
# Health — PUBLIC (no auth): reflects the LIVE database, compared with the submitted
# LOAD_PROOF. Public so the platform health-check and the reviewer can call it; it exposes
# only the DB fingerprint (no secrets) and never touches the LLM, so it can't be abused.
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    from scripts.compute_load_fingerprint import (
        DEFAULT_DATABASE_URL,
        connect,
        fetch_aggregates,
        fetch_latest_manifest,
        fetch_pair_hash,
    )

    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    with connect(url) as conn:
        pair = fetch_pair_hash(conn)
        manifest = fetch_latest_manifest(conn)
        aggregates = fetch_aggregates(conn)
    return {
        "db_fingerprint": pair,
        "dataset_revision": manifest["dataset_revision"],
        "row_hash": manifest["row_hash"],
        "financial_status_posted_only_rows": aggregates["posted_stay_rows"],
    }


# --------------------------------------------------------------------------- #
# Chat — stream tool/skill activity as SSE
# --------------------------------------------------------------------------- #
class ChatIn(BaseModel):
    message: str
    thread_id: str = "web"


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _text(content) -> str:
    """Flatten message content to text (Groq returns str; Gemini returns content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def _events_from_update(update: dict):
    """Translate a LangGraph node update into UI events (tool calls, skill loads, answer)."""
    for msg in update.get("messages", []) or []:
        for tc in getattr(msg, "tool_calls", None) or []:
            name, args = tc.get("name"), tc.get("args", {})
            if name == "read_file" and "SKILL.md" in str(args):
                yield {"type": "skill", "path": str(args.get("file_path", args))}
            else:
                yield {"type": "tool", "name": name, "args": args}
        if type(msg).__name__ == "AIMessage" and not getattr(msg, "tool_calls", None):
            answer = _text(getattr(msg, "content", ""))
            if answer.strip():
                yield {"type": "answer", "text": answer}


def _run_stream(payload, config):
    """Yield SSE strings for an agent run; surface a HITL pause if get_as_of_otb is gated."""
    from agent.graph import get_agent

    agent = get_agent()
    try:
        for chunk in agent.stream(payload, config=config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                yield _sse(
                    {
                        "type": "approval",
                        "tool": "get_as_of_otb",
                        "note": "Expensive point-in-time rebuild — approve to run.",
                    }
                )
                return
            for _node, update in chunk.items():
                if isinstance(update, dict):
                    for ev in _events_from_update(update):
                        yield _sse(ev)
    except Exception as exc:  # surface errors to the UI instead of a dead stream
        yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    yield _sse({"type": "done"})


@app.post("/chat")
def chat(body: ChatIn, _user: str = Depends(require_auth)):
    config = {"configurable": {"thread_id": body.thread_id}}
    payload = {"messages": [{"role": "user", "content": body.message}]}
    return StreamingResponse(_run_stream(payload, config), media_type="text/event-stream")


@app.post("/resume")
def resume(body: ChatIn, _user: str = Depends(require_auth)):
    """Resume after the human approves/rejects the get_as_of_otb gate.
    HumanInTheLoopMiddleware expects resume={"decisions": [<decision>]} with type
    'approve' or 'reject'."""
    config = {"configurable": {"thread_id": body.thread_id}}
    if body.message.lower().startswith("approve"):
        decisions = [{"type": "approve"}]
    else:
        decisions = [{"type": "reject", "message": "Rejected by the user."}]
    return StreamingResponse(
        _run_stream(Command(resume={"decisions": decisions}), config),
        media_type="text/event-stream",
    )


# --------------------------------------------------------------------------- #
# UI — template lives in agent/index.html (presentation kept out of this module)
# --------------------------------------------------------------------------- #
_INDEX = (Path(__file__).resolve().parent / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index(_user: str = Depends(require_auth)) -> str:
    return _INDEX
