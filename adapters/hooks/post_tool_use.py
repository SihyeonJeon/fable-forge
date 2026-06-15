#!/usr/bin/env python3
"""PostToolUse: record which files an edit touched, so the done gate can VERIFY
the implementation did not conflict with the architecture/policy the spec declared
(forbidden_paths) — not just that the spec declared them.

Append-only, deduped, hook-side (zero model tokens). Records only while a task is
active. Never blocks (observational). Runtime-agnostic (Claude Code + Codex)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_payload, project_root, run_gate, tool_name, edited_paths, under_wfb, EDIT_TOOLS  # noqa: E402


def main() -> int:
    if os.environ.get("WFB_BYPASS") == "1":
        return 0
    payload = read_payload()
    if tool_name(payload) not in EDIT_TOOLS:
        return 0
    root = project_root(payload)
    if run_gate("active", "--root", root)[0] != 0:
        return 0
    # canonical containment, not substring (so '.wfb/../src/a.py' is recorded, and a
    # symlinked '.wfb' alias can't smuggle an edit out of the log)
    paths = [p for p in edited_paths(payload) if not under_wfb(p, root)]
    if not paths:
        return 0
    log = Path(root) / ".wfb" / "edits.txt"
    try:
        existing = set(log.read_text(encoding="utf-8").splitlines()) if log.exists() else set()
        new = [p for p in paths if p not in existing]
        if new:
            with log.open("a", encoding="utf-8") as f:
                for p in new:
                    f.write(p + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(f"wfb post_tool_use error (failing open): {exc}\n")
        raise SystemExit(0)
