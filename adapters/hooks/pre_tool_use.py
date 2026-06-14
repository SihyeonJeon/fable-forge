#!/usr/bin/env python3
"""PreToolUse: block implementation edits until the SPEC gate passes.

Runtime-agnostic: Claude Code (Edit/Write, exit 2 blocks) and Codex (apply_patch,
exit 2 blocks). Model-agnostic — enforces for any model whenever a task is active.
Edits to `.forge/` (authoring the spec) are always allowed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (read_payload, project_root, run_gate, tool_name,  # noqa: E402
                    edit_targets_blob, edited_paths, is_off, session_id, EDIT_TOOLS)


def _is_forge(p: str) -> bool:
    return ".forge/" in p or p.rstrip("/").endswith(".forge")


def main() -> int:
    if os.environ.get("FORGE_BYPASS") == "1":
        return 0
    payload = read_payload()
    if tool_name(payload) not in EDIT_TOOLS:
        return 0
    root = project_root(payload)
    if is_off(root, session_id(payload)):
        return 0  # gate toggled off at session/project/machine scope

    # No determinable edit target (degenerate payload / unknown future tool shape):
    # fail OPEN so a tool-shape change can never brick the host's edit pipeline.
    if not edit_targets_blob(payload).strip():
        return 0

    # Exempt authoring the spec ONLY when every parsed edit target is a .forge
    # artifact. A substring match on the whole command is gameable (a real-file edit
    # whose patch text merely mentions ".forge/" would bypass), so require all paths.
    paths = edited_paths(payload)
    if paths:
        if all(_is_forge(p) for p in paths):
            return 0
        # real (non-.forge) file present -> do NOT exempt; gate it
    elif ".forge/" in edit_targets_blob(payload):
        return 0  # couldn't parse paths but references .forge -> conservative allow

    if run_gate("active", "--root", root)[0] != 0:
        return 0  # no active task -> nothing to enforce

    rc, out = run_gate("validate", "--root", root, "--gate", "spec")
    if rc != 0:
        sys.stderr.write(
            "fable-forge: implementation blocked — SPEC gate not satisfied.\n"
            "Author .forge/spec.json per the engineering procedure (restated_goal, "
            "non_goals, must_read, >=2 rejected_alternatives, >=1 invariant, risks, "
            "acceptance_criteria), then retry the edit.\n\n" + out.strip() + "\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(f"fable-forge pre_tool_use error (failing open): {exc}\n")
        raise SystemExit(0)
