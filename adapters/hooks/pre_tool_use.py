#!/usr/bin/env python3
"""PreToolUse: block implementation edits until the SPEC gate passes.

Runtime-agnostic: Claude Code (Edit/Write, exit 2 blocks) and Codex (apply_patch,
exit 2 blocks). Model-agnostic — enforces for any model whenever a task is active.
Edits to `.forge/` (authoring the spec) are always allowed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (read_payload, project_root, run_gate, tool_name,  # noqa: E402
                    edit_targets_blob, edited_paths, is_off, session_id,
                    under_forge, is_spec_authoring, EDIT_TOOLS)


def _is_protected_state(p: str, root: str) -> bool:
    """Gate-controlled state (GRADE / ACTIVE / edits.txt / STATE / OFF / sessions/...) —
    a model writing these could downgrade its own enforcement, so it is never allowed.
    Canonical containment (not substring) so '.forge/../x' or symlink aliases can't bypass."""
    return under_forge(p, root) and not is_spec_authoring(p, root)


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
        if any(_is_protected_state(p, root) for p in paths):
            sys.stderr.write(
                "wfb: editing gate state (.forge/GRADE | ACTIVE | edits.txt | "
                "STATE | sessions) is not allowed — it would let an active task downgrade "
                "its own enforcement. Author .forge/spec.json only.\n")
            return 2
        spec_targets = [p for p in paths if is_spec_authoring(p, root)]
        if spec_targets and len(spec_targets) != len(paths):
            # A single patch that edits spec.json AND implementation files would be validated
            # against the OLD on-disk spec, letting it soften the spec and land code at once.
            sys.stderr.write(
                "wfb: do not edit .forge/spec.json and implementation files in the "
                "same change — write the spec in its own tool call, let the gate validate it, "
                "then edit code separately.\n")
            return 2
        if spec_targets:
            return 0  # authoring the spec artifact only -> allowed
        # real (non-.forge) file present -> do NOT exempt; gate it
    elif ".forge/" in edit_targets_blob(payload):
        return 0  # couldn't parse paths but references .forge -> conservative allow

    if run_gate("active", "--root", root)[0] != 0:
        return 0  # no active task -> nothing to enforce

    # Pass the files THIS edit will touch so multi-file escalation (LIGHT->STANDARD) is
    # decided before the spreading edit is authorized, not backfilled at done. Passed via
    # env (NOT argv) so a path like '--pending' / '--root' can't inject gate arguments.
    pend = [p for p in paths if not under_forge(p, root)]
    if pend:
        os.environ["FORGE_PENDING"] = json.dumps(pend)
    rc, out = run_gate("validate", "--root", root, "--gate", "spec")
    if rc != 0:
        sys.stderr.write(
            "wfb: implementation blocked — SPEC gate not satisfied.\n"
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
        sys.stderr.write(f"wfb pre_tool_use error (failing open): {exc}\n")
        raise SystemExit(0)
