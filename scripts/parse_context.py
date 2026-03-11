#!/usr/bin/env python3
"""
Parse a MassGen agent context.txt file and show:
  - Each conversation history turn (role + content summary)
  - new_answer tool calls highlighted (agent's own submitted answers)
  - The CURRENT ANSWERS block from user_message (what other agents submitted)

Usage:
    python scripts/parse_context.py <path/to/context.txt>
    python scripts/parse_context.py <path/to/log_dir>   # auto-finds context.txt files
"""

import json
import sys
import re
from pathlib import Path


SEPARATOR = "=" * 80
THIN = "-" * 60


def extract_new_answer_content(content) -> str | None:
    """Return the answer text if this content block contains a new_answer tool call."""
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "new_answer":
                inp = block.get("input", {})
                return inp.get("answer") or inp.get("content") or json.dumps(inp)[:300]
    if isinstance(content, str) and "new_answer" in content:
        return content[:500]
    return None


def extract_vote_content(content) -> str | None:
    """Return vote info if this content block contains a vote tool call."""
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "vote":
                inp = block.get("input", {})
                return json.dumps(inp)
    return None


def extract_tool_calls(content) -> list[str]:
    """Return list of tool call names in this content."""
    calls = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append(block.get("name", "?"))
    return calls


def content_text(content, max_chars=300) -> str:
    """Get a short readable version of message content."""
    if isinstance(content, str):
        return content[:max_chars].replace("\n", "↵")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", "")[:max_chars])
                elif block.get("type") == "tool_use":
                    parts.append(f"[TOOL: {block.get('name')}]")
                elif block.get("type") == "tool_result":
                    parts.append(f"[TOOL_RESULT: {str(block.get('content',''))[:100]}]")
        return " | ".join(parts)[:max_chars]
    return str(content)[:max_chars]


def extract_current_answers(user_message: str) -> list[tuple[str, str]]:
    """Extract [agentN] -> answer pairs from the CURRENT ANSWERS block."""
    answers = []
    # Find the CURRENT ANSWERS section
    match = re.search(r"<CURRENT ANSWERS[^>]*>(.*?)(?:</CURRENT ANSWERS>|$)", user_message, re.DOTALL)
    if not match:
        return answers
    block = match.group(1)
    # Each answer starts with <agentX.Y> or <agentX>
    entries = re.split(r"(<agent\d+(?:\.\d+)?>)", block)
    label = None
    for part in entries:
        part = part.strip()
        if re.match(r"^<agent\d+(?:\.\d+)?>$", part):
            label = part
        elif label and part:
            answers.append((label, part))
            label = None
    return answers


def parse_context(path: Path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    history = data.get("conversation_history", [])
    user_message = data.get("user_message", "")
    system_message = data.get("system_message", "")

    print(SEPARATOR)
    print(f"FILE: {path}")
    print(SEPARATOR)
    print(f"system_message: {len(system_message)} chars | "
          f"user_message: {len(user_message)} chars | "
          f"history turns: {len(history)}")
    print()

    # --- Conversation history ---
    print(SEPARATOR)
    print(f"CONVERSATION HISTORY ({len(history)} turns)")
    print(SEPARATOR)

    new_answer_count = 0
    for i, turn in enumerate(history, 1):
        role = turn.get("role", "?")
        content = turn.get("content", "")

        new_answer_text = extract_new_answer_content(content)
        vote_text = extract_vote_content(content)
        tool_calls = extract_tool_calls(content)

        if new_answer_text:
            new_answer_count += 1
            print(f"\n[turn {i}] role={role}  ★ NEW_ANSWER #{new_answer_count}")
            print(THIN)
            print(new_answer_text[:600])
            print(THIN)
        elif vote_text:
            print(f"\n[turn {i}] role={role}  → VOTE: {vote_text}")
        elif tool_calls:
            print(f"[turn {i}] role={role}  tools={tool_calls}  | {content_text(content)}")
        else:
            short = content_text(content, max_chars=120)
            print(f"[turn {i}] role={role}  | {short}")

    print()
    print(f"  Total new_answer submissions in history: {new_answer_count}")
    if new_answer_count > 0:
        print("  ⚠  Agent has memory of its own answer content — self-identification risk if own answer appears below.")
    else:
        print("  ✓  No new_answer turns — agent has no memory of its own submitted content.")

    # --- CURRENT ANSWERS block ---
    print()
    print(SEPARATOR)
    print("CURRENT ANSWERS shown to agent (from user_message)")
    print(SEPARATOR)

    answers = extract_current_answers(user_message)
    if not answers:
        print("  (no CURRENT ANSWERS block found in user_message)")
    else:
        for label, ans_text in answers:
            print(f"\n{label}")
            print(ans_text[:800])
            print()

    # --- Verdict ---
    print(SEPARATOR)
    if new_answer_count > 0 and answers:
        print("VERDICT: ⚠  Agent has own answer history + sees anonymous answers.")
        print("   It can compare its history content to the answers above and self-identify.")
    elif new_answer_count > 0:
        print("VERDICT: ✓  Agent has history but no anonymous answers block — cannot self-identify.")
    else:
        print("VERDICT: ✓  Clean — agent has no memory of its own answer.")
    print(SEPARATOR)


def find_context_files(root: Path) -> list[Path]:
    return sorted(root.rglob("context.txt"))


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/parse_context.py <context.txt or log_dir>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if target.is_file():
        parse_context(target)
    elif target.is_dir():
        files = find_context_files(target)
        if not files:
            print(f"No context.txt files found under {target}")
            sys.exit(1)
        for f in files:
            parse_context(f)
            print()
    else:
        print(f"Not found: {target}")
        sys.exit(1)


if __name__ == "__main__":
    main()
