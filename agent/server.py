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
                yield _sse({"type": "approval", "tool": "get_as_of_otb",
                            "note": "Expensive point-in-time rebuild — approve to run."})
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
# Minimal UI
# --------------------------------------------------------------------------- #
_INDEX = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grand Harbour Hotel — Revenue Manager</title>
<style>
 :root{--bg:#f4f6f8;--card:#fff;--ink:#1c2733;--muted:#64748b;--accent:#15616d;--accent2:#0d3b43;
       --line:#e3e9ef;--user:#15616d;--gold:#b8893a}
 *{box-sizing:border-box}
 body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      background:var(--bg);color:var(--ink)}
 header{background:linear-gradient(135deg,#0d3b43,#15616d);color:#fff;padding:16px 22px;
        position:sticky;top:0;z-index:5;box-shadow:0 2px 10px rgba(0,0,0,.08)}
 header .h{font-size:18px;font-weight:700;letter-spacing:.3px}
 header .s{font-size:13px;opacity:.85;margin-top:2px}
 #log{max-width:880px;margin:0 auto;padding:24px 16px 130px}
 .row{display:flex;margin:16px 0}
 .bubble{padding:12px 16px;border-radius:16px;max-width:82%;box-shadow:0 1px 2px rgba(20,40,60,.06);
         white-space:normal;word-wrap:break-word}
 .user{margin-left:auto;background:var(--user);color:#fff;border-bottom-right-radius:5px}
 .bot{background:var(--card);border:1px solid var(--line);border-bottom-left-radius:5px}
 .turn{margin:16px 0}
 .activity{max-width:82%;margin-bottom:8px;background:#eef3f6;border:1px solid var(--line);
           border-radius:12px;padding:6px 12px;font-size:12.5px;color:var(--muted)}
 .activity summary{cursor:pointer;font-weight:600;color:var(--accent);list-style:none;user-select:none}
 .activity summary::-webkit-details-marker{display:none}
 .activity summary:before{content:"\25B8 ";color:var(--muted)}
 .activity[open] summary:before{content:"\25BE "}
 .step{padding:3px 2px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
 .spinner{color:var(--muted);font-style:italic}
 form{position:fixed;bottom:0;left:0;right:0;background:rgba(244,246,248,.94);
      border-top:1px solid var(--line);backdrop-filter:blur(8px)}
 .bar{max-width:880px;margin:auto;display:flex;gap:10px;padding:12px 16px}
 input{flex:1;padding:12px 15px;border:1px solid var(--line);border-radius:12px;background:#fff;
        font-size:15px;outline:none}
 input:focus{border-color:var(--accent)}
 button{padding:12px 20px;border:0;border-radius:12px;background:var(--accent);color:#fff;
         font-weight:600;cursor:pointer}
 button:hover{background:var(--accent2)}
 .approve{margin-top:10px;background:var(--gold);padding:9px 16px}
</style></head><body>
<header>
  <div class="h">Grand Harbour Hotel</div>
  <div class="s">Revenue Manager</div>
</header>
<div id="log"></div>
<form id="f"><div class="bar">
  <input id="q" autocomplete="off"
   placeholder="e.g. What's driving September 2026?  ·  Are we too dependent on OTA?">
  <button>Ask</button>
</div></form>
<script>
const log=document.getElementById('log'),f=document.getElementById('f'),q=document.getElementById('q');
const tid='web-'+Math.random().toString(36).slice(2);
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function md(t){return esc(t).replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/\n/g,'<br>');}
function scroll(){window.scrollTo(0,document.body.scrollHeight);}
function bubble(cls,html){const d=document.createElement('div');d.className='bubble '+cls;d.innerHTML=html;return d;}
function userRow(m){const r=document.createElement('div');r.className='row';r.appendChild(bubble('user',esc(m)));log.appendChild(r);}

function newTurn(){
  const turn=document.createElement('div');turn.className='turn';
  const act=document.createElement('details');act.className='activity';act.open=true;
  act.innerHTML='<summary>Agent activity</summary>';
  const ans=bubble('bot','<span class="spinner">thinking…</span>');
  turn.appendChild(act);turn.appendChild(ans);log.appendChild(turn);
  return {act,ans,count:0};
}
function step(t,html){t.count++;const d=document.createElement('div');d.className='step';d.innerHTML=html;t.act.appendChild(d);scroll();}

async function send(url,message,turn){
  const t=turn||newTurn();
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
                          body:JSON.stringify({message,thread_id:tid})});
  const reader=r.body.getReader();const dec=new TextDecoder();let buf='';
  while(true){const {value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});
    let i;while((i=buf.indexOf('\n\n'))>=0){const line=buf.slice(0,i).replace(/^data: /,'');buf=buf.slice(i+2);
      if(!line)continue;let e;try{e=JSON.parse(line);}catch(_){continue;}
      if(e.type==='tool'){
        if(e.name==='task'){step(t,'🤝 delegating to sub-agent: '+esc((e.args&&e.args.subagent_type)||'segment-analyst'));}
        else{const a=Object.entries(e.args||{}).map(function(kv){return kv[0]+'='+kv[1];}).join(', ');
             step(t,'🔧 '+esc(e.name)+(a?' ('+esc(a)+')':''));}
      }
      else if(e.type==='skill'){step(t,'📖 skill: '+esc(e.path.split('/').slice(-2)[0]));}
      else if(e.type==='answer'){t.ans.innerHTML=md(e.text);scroll();}
      else if(e.type==='approval'){
        t.ans.innerHTML='⏸ <b>Approval needed</b> to run '+esc(e.tool)+'. '+esc(e.note||'');
        const b=document.createElement('button');b.className='approve';b.textContent='Approve & run';
        b.onclick=function(){b.remove();t.ans.innerHTML='<span class="spinner">running…</span>';send('/resume','approve',t);};
        t.ans.appendChild(document.createElement('br'));t.ans.appendChild(b);scroll();
      }
      else if(e.type==='error'){t.ans.innerHTML='⚠ '+esc(e.message);}
      else if(e.type==='done'){if(t.count===0){t.act.remove();}else{t.act.open=false;}}
    }}
}
f.onsubmit=function(ev){ev.preventDefault();const m=q.value.trim();if(!m)return;userRow(m);q.value='';scroll();send('/chat',m);};
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index(_user: str = Depends(require_auth)) -> str:
    return _INDEX
