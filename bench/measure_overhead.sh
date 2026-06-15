#!/usr/bin/env bash
# Measure wfb token overhead: same task, naked codex vs single-session wfb-codex.
# Target: cache_adj overhead < 2.0x.  Uses gpt-5.5 at WFB_EFFORT (default medium).
set +e
WFB="$(cd "$(dirname "$0")/.." && pwd)"
SUM="python3 $FORGE/bench/sum_tokens.py"
EFFORT="${WFB_EFFORT:-medium}"
TASK="${BENCH_TASK:-Add a function slugify(s) to slug.py: lowercase the input, replace runs of non-alphanumeric characters with a single hyphen, and strip leading/trailing hyphens. Add a pytest test file test_slug.py with 3 cases. Stdlib only.}"
B=/tmp/wfb_bench; rm -rf "$B"; mkdir -p "$B"

echo "=== ARM naked (codex exec, effort=$EFFORT) ==="
N="$B/naked"; mkdir -p "$N"; (cd "$N" && git init -q)
( cd "$N" && codex exec --json --skip-git-repo-check -s workspace-write \
    -c model=gpt-5.5 -c model_reasoning_effort="$EFFORT" "$TASK" < /dev/null > run.jsonl 2>/dev/null )
naked="$($SUM "$N/run.jsonl")"
echo "$naked"

echo "=== ARM wfbd (wfb-codex, single session, effort=$EFFORT) ==="
F="$B/wfbd"; mkdir -p "$F"; (cd "$F" && git init -q)
( cd "$F" && WFB_EFFORT="$EFFORT" "$FORGE/adapters/codex/wfb-codex.sh" "$TASK" )
wfbd="$($SUM "$F/.wfb/codex_run.jsonl")"
echo "$wfbd"

echo "=== RESULT ==="
python3 - "$naked" "$wfbd" <<'PY'
import json, sys
n = json.loads(sys.argv[1]); f = json.loads(sys.argv[2])
print(f"naked : {n}")
print(f"wfbd: {f}")
for k in ("raw_total", "cache_adj"):
    r = (f[k] / n[k]) if n[k] else 0.0
    verdict = "PASS (<2x)" if 0 < r < 2 else "OVER 2x"
    print(f"  {k:9s} wfbd/naked = {r:.2f}x  -> {verdict}")
PY
echo "=== artifacts ==="
echo "naked files:";  ls "$N" 2>/dev/null
echo "wfbd files:"; ls "$F" 2>/dev/null; echo "wfbd spec gate:"; python3 "$FORGE/gates/wfb_gate.py" status --root "$F" 2>/dev/null
