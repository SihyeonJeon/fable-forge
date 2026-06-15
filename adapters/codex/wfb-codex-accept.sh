#!/usr/bin/env bash
# wfb-codex-accept — headless Codex enforcement by DISPOSABLE WORKTREE + post-run
# acceptance gate. Co-designed with Codex (cross-verified) because `codex exec` cannot
# hard-block file writes: edits surface as native `file_change` items that bypass the
# PreToolUse/apply_patch hook ("file change approval is not supported in exec mode").
#
# Mechanism: the worker runs in a throwaway git worktree. Its diff is applied to the
# real repo ONLY if the spec + done gate passes (and it touched no forbidden path).
# The real repo is never mutated by unspeced/forbidden work. Structurally ONE codex
# invocation (not the wrapper's 3), but the gated worker does more — write a full spec +
# run real verification — so measured cost is over 2x a naked run on STANDARD (TOKEN_BUDGET.md).
#
#   wfb-codex-accept "<goal>" [--repo DIR]
#   WFB_MODEL=gpt-5.5 WFB_EFFORT=medium wfb-codex-accept "<goal>"
set -euo pipefail

# Resolve through symlinks — this script is installed onto PATH as a symlink, so $0 is
# the link, not the real file; dirname "$0" would point at the bin dir, breaking ../../gates.
SELF="$0"
while [ -h "$SELF" ]; do d="$(cd "$(dirname "$SELF")" && pwd)"; SELF="$(readlink "$SELF")"; case "$SELF" in /*) ;; *) SELF="$d/$SELF";; esac; done
HERE="$(cd "$(dirname "$SELF")" && pwd)"
GATE="$(cd "$HERE/../../gates" && pwd)/wfb_gate.py"
REPO="$PWD"; MODEL="${WFB_MODEL:-gpt-5.5}"; EFFORT="${WFB_EFFORT:-}"; GOAL=""
while [ $# -gt 0 ]; do case "$1" in --repo) REPO="$2"; shift 2;; *) GOAL="$1"; shift;; esac; done
[ -n "$GOAL" ] || { echo "usage: wfb-codex-accept \"<goal>\" [--repo DIR]" >&2; exit 2; }

REPO="$(cd "$REPO" && pwd)"
# Indicator (Codex has no custom status line like Claude Code, so we announce on the
# stream instead): make it obvious the gate is mediating this run.
echo "[why-was-fable-banned] gate active — worktree-accept (only a gate-passing diff reaches $REPO)" >&2
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { echo "wfb: --repo must be a git repo" >&2; exit 2; }
BASE="$(git -C "$REPO" rev-parse HEAD)"
WT="${TMPDIR:-/tmp}/wfb-run-$(git -C "$REPO" rev-parse --short HEAD)-$$"
cleanup(){ [ -n "${WFB_KEEP:-}" ] && { echo "wfb: worktree kept at $WT" >&2; return 0; }
           git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; }
trap cleanup EXIT

git -C "$REPO" worktree add --detach "$WT" "$BASE" >/dev/null 2>&1
python3 "$GATE" scaffold --root "$WT" --goal "$GOAL" >/dev/null
# Same grade-specific contract the Claude hook injects — generated from the gate's own
# rules so the model writes a first-try-passing spec instead of discovering each rule by
# being rejected (every such resume round re-bills the whole context).
CONTRACT="$(python3 "$GATE" contract --root "$WT" 2>/dev/null)"

OPTS=(--json --skip-git-repo-check -s workspace-write -m "$MODEL")
[ -n "$EFFORT" ] && OPTS+=(-c model_reasoning_effort="$EFFORT")
RUNLOG="$WT/.wfb/codex_run.jsonl"
codex exec "${OPTS[@]}" -C "$WT" "Task: ${GOAL}

${CONTRACT}

List globs you must not modify in forbidden_paths. After the spec passes, implement the
smallest change, then run EACH acceptance command and write its live output into that
criterion's \"evidence\". Do not fabricate evidence." \
  < /dev/null > "$RUNLOG" 2>/dev/null || true

# Hooks don't fire in exec, so derive the REAL edit set from git for the forbidden check.
refresh_edits(){ git -C "$WT" add -A >/dev/null 2>&1 || true
  git -C "$WT" diff --cached --name-only "$BASE" 2>/dev/null | grep -v '^\.wfb/' > "$WT/.wfb/edits.txt" || true; }
refresh_edits

# Verify-retry: don't discard good work over a missing evidence field — resume the SAME
# session up to WFB_DONE_TRIES to finish/verify before rejecting (still fail-closed).
TID="$(python3 - "$RUNLOG" 2>/dev/null <<'PY'
import json, sys
tid = ""
for ln in open(sys.argv[1], encoding="utf-8", errors="replace"):
    ln = ln.strip()
    if ln[:1] == "{":
        try: o = json.loads(ln)
        except Exception: continue
        if o.get("type") == "thread.started" and o.get("thread_id"): tid = o["thread_id"]
print(tid)
PY
)"
RESUME_OPTS=(--json --skip-git-repo-check -m "$MODEL")
[ -n "$EFFORT" ] && RESUME_OPTS+=(-c model_reasoning_effort="$EFFORT")
DONE_TRIES="${WFB_DONE_TRIES:-2}"
try=0
while ! python3 "$GATE" validate --root "$WT" --gate done >/dev/null 2>&1; do
  [ -n "$TID" ] && [ "$try" -lt "$DONE_TRIES" ] || break
  try=$((try + 1))
  errs="$(python3 "$GATE" validate --root "$WT" --gate done 2>&1 || true)"
  ( cd "$WT" && codex exec resume "${RESUME_OPTS[@]}" "$TID" "The done gate is unmet. Fix EXACTLY these, then stop:
${errs}
Run each acceptance_criteria command and write its live output into that criterion's \"evidence\" in .wfb/spec.json. If the implementation is incomplete, finish the smallest change first. Do not fabricate output." \
    < /dev/null >> "$RUNLOG" 2>/dev/null ) || true
  refresh_edits
done

if python3 "$GATE" validate --root "$WT" --gate done; then
  git -C "$WT" diff --cached --binary "$BASE" > "$WT/accepted.patch" 2>/dev/null || true
  if [ -s "$WT/accepted.patch" ]; then
    git -C "$REPO" apply --index --allow-empty "$WT/accepted.patch" 2>/dev/null \
      && echo "wfb-codex-accept: ACCEPTED — gate passed; diff applied to $REPO (staged)." \
      || { echo "wfb-codex-accept: gate passed but patch did not apply cleanly (real repo dirty?). Patch at $WT kept." >&2; trap - EXIT; exit 3; }
  else
    echo "wfb-codex-accept: gate passed but produced no diff."
  fi
  exit 0
else
  echo "wfb-codex-accept: REJECTED — done gate unmet. Real repo UNTOUCHED; worktree discarded." >&2
  exit 1
fi
