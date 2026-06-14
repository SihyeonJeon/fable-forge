"""Shared helpers for fable-forge hooks — runtime-agnostic (Claude Code + Codex).
Both runtimes deliver a JSON stdin payload with tool_name/tool_input/cwd and accept
exit code 2 (+ stderr) as a tool-call block. Stdlib only, fail-open."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# adapters/hooks/<file>.py -> adapters -> fable-forge -> gates/forge_gate.py
GATE = Path(__file__).resolve().parents[2] / "gates" / "forge_gate.py"

# Claude Code edit tools + Codex's apply_patch (the tool_name Codex reports for edits).
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "create_file", "str_replace", "apply_patch"}

_PATCH_FILE_RE = re.compile(r"\*\*\* (?:Update|Add|Delete) File:\s*(.+)")


def read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def project_root(payload: dict) -> str:
    r = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    try:
        return str(Path(r).resolve())
    except Exception:
        return str(r)


def run_gate(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run([sys.executable, str(GATE), *args],
                           capture_output=True, text=True, timeout=20)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 0, f"forge gate skipped: {exc}"


def is_off(root) -> bool:
    """Gate disabled for this project (toggled in-session with 'forge off')."""
    return (Path(root) / ".forge" / "OFF").exists()


def tool_name(payload: dict) -> str:
    return payload.get("tool_name", "") or ""


def edited_paths(payload: dict) -> list[str]:
    """Real file paths an edit touches, for BOTH runtimes:
    Claude Code -> tool_input.file_path/path; Codex apply_patch -> parsed from the
    `*** Update/Add/Delete File:` lines in tool_input.command."""
    ti = payload.get("tool_input") or {}
    out: list[str] = []
    for k in ("file_path", "path", "notebook_path"):
        v = ti.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    cmd = ti.get("command")
    if isinstance(cmd, str) and "*** " in cmd:
        out += [m.strip() for m in _PATCH_FILE_RE.findall(cmd)]
    return out


def edit_targets_blob(payload: dict) -> str:
    """A single string covering every path/command an edit references — used only
    for the cheap `.forge/` self-authoring exemption."""
    ti = payload.get("tool_input") or {}
    return " ".join(str(ti.get(k, "")) for k in ("file_path", "path", "notebook_path", "command"))
