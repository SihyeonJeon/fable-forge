#!/usr/bin/env python3
"""UserPromptSubmit: in-session on/off toggle + auto-start a gated task.

- `forge off` / `forge on` / `forge status` are handled by the hook (never sent to
  the model) and toggle the gate for this project.
- Otherwise, a work-shaped prompt auto-starts a gated task (scaffold + procedure).
Runtime-agnostic.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_payload, project_root, run_gate  # noqa: E402

TOGGLE_OFF = {"forge off", "/forge off", "forge:off", "forge stop"}
TOGGLE_ON = {"forge on", "/forge on", "forge:on", "forge start"}
TOGGLE_STATUS = {"forge status", "/forge status", "forge?"}

NOTICE = (
    "[fable-forge] A gated engineering task is now active. Before editing any "
    "implementation file you must write .forge/spec.json: restated_goal (intent + "
    "constraint envelope, not the raw ask), non_goals, must_read (real files chosen "
    "by authority, with reasons), >=1 constraints.invariant, >=2 rejected_alternatives "
    "(category + the boundary each breaks), risks (severity by blast radius + runnable "
    "mitigation), acceptance_criteria (runnable commands). List any architecture/policy "
    "files you must NOT touch in forbidden_paths. Edits are blocked until the SPEC gate "
    "passes; close only when every acceptance criterion cites live evidence. Toggle off "
    "anytime by typing 'forge off'. Do not narrate this to the user."
)


def emit_context(text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": text}}))


def emit_block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))


def main() -> int:
    if os.environ.get("FORGE_BYPASS") == "1":
        return 0
    payload = read_payload()
    root = project_root(payload)
    prompt = (payload.get("prompt", "") or "").strip()
    off = Path(root) / ".forge" / "OFF"

    # in-session toggle — handled here, never reaches the model
    low = prompt.lower()
    if low in TOGGLE_OFF:
        off.parent.mkdir(parents=True, exist_ok=True)
        off.write_text("", encoding="utf-8")
        emit_block("fable-forge: gate OFF for this project. Type 'forge on' to re-enable.")
        return 0
    if low in TOGGLE_ON:
        if off.exists():
            off.unlink()
        emit_block("fable-forge: gate ON. Work prompts auto-start a gated task; edits "
                   "are blocked until the spec passes.")
        return 0
    if low in TOGGLE_STATUS:
        emit_block(f"fable-forge: gate is {'OFF' if off.exists() else 'ON'} for this project.")
        return 0

    if off.exists():
        return 0
    if run_gate("active", "--root", root)[0] == 0:
        return 0  # already active
    if run_gate("classify", "--text", prompt)[0] != 0:
        return 0  # not work-shaped

    run_gate("scaffold", "--root", root, "--goal", prompt[:500])
    emit_context(NOTICE)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(f"fable-forge user_prompt_submit error (failing open): {exc}\n")
        raise SystemExit(0)
