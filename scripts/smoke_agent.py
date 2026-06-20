"""
Live smoke test: ask the Revenue Manager agent a question and print the trace —
every tool call and skill load (a skill load shows up as a read_file on a SKILL.md),
then the final answer. Requires GROQ_API_KEY in .env.

Usage:
  .venv/bin/python -m scripts.smoke_agent "What's driving September 2026?"
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from agent.graph import build_agent  # noqa: E402


def text_of(content) -> str:
    """Flatten message content to plain text (Groq returns str; Gemini returns content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def run(question: str, thread: str = "smoke-1") -> None:
    agent = build_agent()
    config = {"configurable": {"thread_id": thread}}
    print(f"\nQ: {question}\n" + "-" * 70)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config=config)

    for m in result["messages"]:
        for tc in getattr(m, "tool_calls", None) or []:
            name, args = tc["name"], tc.get("args", {})
            if name == "read_file" and "SKILL.md" in str(args):
                print(f"  [SKILL LOAD ] {args.get('file_path', args)}")
            else:
                print(f"  [TOOL CALL  ] {name}({args})")
        if type(m).__name__ == "ToolMessage":
            content = str(m.content).replace("\n", " ")
            print(f"  [TOOL RESULT] {getattr(m, 'name', '?')}: {content[:140]}")

    print("\n=== ANSWER ===")
    print(text_of(result["messages"][-1].content))


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "What's driving September 2026?"
    run(q)
