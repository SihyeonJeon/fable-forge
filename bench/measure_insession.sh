#!/usr/bin/env bash
# Measure the IN-SESSION token overhead: same task, one codex session each —
# naked vs native-hook-gated (repo-local .codex/hooks.json).
# CAVEAT: Codex native PreToolUse hooks do NOT fire under `codex exec` (headless) in
# 0.139 (see ENFORCEMENT.md), so this script measures a real gate only in the interactive
# `codex` TUI. For headless token numbers use bench/measure_tokens.sh (claude -p + Codex
# worktree-accept), which is the path actually shipped.
set +e
WFB="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS="$FORGE/adapters/hooks"
SUM="python3 $FORGE/bench/sum_tokens.py"
EFFORT="${WFB_EFFORT:-medium}"
TASK="${BENCH_TASK:-Add a function slugify(s) to slug.py: lowercase the input, replace runs of non-alphanumeric characters with a single hyphen, strip leading/trailing hyphens. Add a pytest test file test_slug.py with 3 cases. Stdlib only.}"
B=/tmp/wfb_bench_is; rm -rf "$B"; mkdir -p "$B"
COMMON=(--json --skip-git-repo-check -s workspace-write -c model=gpt-5.5 -c model_reasoning_effort="$EFFORT")

echo "=== ARM naked ==="
N="$B/naked"; mkdir -p "$N"; (cd "$N" && git init -q)
( cd "$N" && codex exec "${COMMON[@]}" "$TASK" < /dev/null > run.jsonl 2>/dev/null )
naked="$($SUM "$N/run.jsonl")"; echo "$naked"

echo "=== ARM gated (in-session native hooks) ==="
G="$B/gated"; mkdir -p "$G/.codex"; (cd "$G" && git init -q)
cat > "$G/.codex/hooks.json" <<JSON
{ "hooks": {
  "UserPromptSubmit": [{"hooks":[{"type":"command","command":"python3 \"$HOOKS/user_prompt_submit.py\""}]}],
  "PreToolUse":  [{"matcher":"apply_patch|Edit|Write","hooks":[{"type":"command","command":"python3 \"$HOOKS/pre_tool_use.py\"","timeout":20}]}],
  "PostToolUse": [{"matcher":"apply_patch|Edit|Write","hooks":[{"type":"command","command":"python3 \"$HOOKS/post_tool_use.py\"","timeout":20}]}],
  "Stop": [{"hooks":[{"type":"command","command":"python3 \"$HOOKS/stop.py\""}]}]
} }
JSON
# headless `codex exec` does NOT fire UserPromptSubmit, so the caller scaffolds the
# task first (free, local); the native PreToolUse hook then gates inside ONE session.
python3 "$FORGE/gates/wfb_gate.py" scaffold --root "$G" --goal "$TASK" >/dev/null
( cd "$G" && codex exec "${COMMON[@]}" --dangerously-bypass-hook-trust "$TASK" < /dev/null > run.jsonl 2>/dev/null )
gated="$($SUM "$G/run.jsonl")"; echo "$gated"

echo "=== RESULT ==="
python3 - "$naked" "$gated" <<'PY'
import json, sys
n=json.loads(sys.argv[1]); g=json.loads(sys.argv[2])
print("naked:", n); print("gated:", g)
for k in ("raw_total","cache_adj"):
    r=(g[k]/n[k]) if n[k] else 0.0
    print(f"  {k:9s} gated/naked = {r:.2f}x -> {'PASS (<2x)' if 0<r<2 else 'OVER 2x'}")
PY
echo "=== did the gate engage? ==="
echo "gated .wfb present:"; ls "$G/.wfb" 2>/dev/null && python3 "$FORGE/gates/wfb_gate.py" status --root "$G"
echo "gated spec.json:"; python3 -c "import json;d=json.load(open('$G/.wfb/spec.json'));print('grade',d.get('grade'),'| restated:',d.get('restated_goal','')[:70])" 2>/dev/null || echo "(no spec — UserPromptSubmit may not fire in exec)"
echo "gated produced files:"; ls "$G"/*.py 2>/dev/null
