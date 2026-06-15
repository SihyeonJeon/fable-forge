"""Shared helpers for wfb hooks — runtime-agnostic (Claude Code + Codex).
Both runtimes deliver a JSON stdin payload with tool_name/tool_input/cwd and accept
exit code 2 (+ stderr) as a tool-call block. Stdlib only, fail-open."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# adapters/hooks/<file>.py -> adapters -> wfb -> gates/wfb_gate.py
GATE = Path(__file__).resolve().parents[2] / "gates" / "wfb_gate.py"

# Claude Code edit tools + Codex's apply_patch (the tool_name Codex reports for edits).
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "create_file", "str_replace", "apply_patch"}

# apply_patch headers: "*** Update/Add/Delete File: <path>" and the rename destination
# "*** Move to: <path>" — the move dest must count too, or a rename escapes escalation /
# forbidden-path checks (only the source would be logged).
_PATCH_FILE_RE = re.compile(r"\*\*\* (?:(?:Update|Add|Delete) File|Move to):\s*(.+)")


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
        return 0, f"wfb gate skipped: {exc}"


def session_id(payload: dict) -> str:
    return str(payload.get("session_id") or "")


def is_off(root, sid: str = "") -> bool:
    """Gate disabled at the effective scope (session > project > machine > default on).
    Delegates to the gate's `state` command so there is one resolver. Fails toward ON
    (enforce) if state can't be determined."""
    args = ["state", "--root", str(root)]
    if sid:
        args += ["--sid", str(sid)]
    _, out = run_gate(*args)
    last = (out.strip().splitlines() or [""])[-1].strip().lower()
    return last == "off"


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


def canon_path(p: str, root: str) -> str:
    """Resolved absolute path (follows symlinks, collapses ../ and ./) — substring checks
    on '.wfb/' are bypassable (e.g. '.wfb/../src/a.py', '/other/.wfb/...', a symlink),
    so all gate-state decisions canonicalize first."""
    base = p if os.path.isabs(p) else os.path.join(root, p)
    try:
        return os.path.realpath(base)
    except Exception:
        return os.path.normpath(base)


def under_wfb(p: str, root: str) -> bool:
    """True iff p canonically lives inside <root>/.wfb (this project's gate state)."""
    c = canon_path(p, root)
    wfb = canon_path(".wfb", root)
    return c == wfb or c.startswith(wfb + os.sep)


def is_spec_authoring(p: str, root: str) -> bool:
    """The ONE gate artifact a model may write — exactly <root>/.wfb/spec.json."""
    return canon_path(p, root) == canon_path(os.path.join(".wfb", "spec.json"), root)


def edit_targets_blob(payload: dict) -> str:
    """A single string covering every path/command an edit references — used only
    for the cheap `.wfb/` self-authoring exemption."""
    ti = payload.get("tool_input") or {}
    return " ".join(str(ti.get(k, "")) for k in ("file_path", "path", "notebook_path", "command"))
