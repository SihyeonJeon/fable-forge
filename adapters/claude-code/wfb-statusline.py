#!/usr/bin/env python3
"""Claude Code statusLine segment for wfb.

Prints `[why-was-fable-banned]` when the gate is effectively ON for the current
session/dir/machine, nothing when off. Claude Code feeds this script a JSON object on
stdin (session_id, cwd, workspace, model, ...) and renders its stdout at the bottom.

Use it as your whole statusLine, OR call it from an existing statusLine script and
append its output — it prints only the wfb segment, no newline, so it composes.
Stdlib only; fails silent (never breaks your prompt)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gates"))


def _cwd(d: dict) -> str:
    ws = d.get("workspace") or {}
    return d.get("cwd") or ws.get("current_dir") or ws.get("project_dir") or os.getcwd()


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception:
        d = {}
    try:
        import wfb_gate as fg
        on = fg.effective_state(Path(_cwd(d)).resolve(), d.get("session_id")) == "on"
    except Exception:
        return 0  # never break the user's status line
    if on:
        # dim red so it reads as a warning marker, not chrome
        sys.stdout.write("\x1b[38;5;203m[why-was-fable-banned]\x1b[0m")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
