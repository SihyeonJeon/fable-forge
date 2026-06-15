#!/usr/bin/env bash
# Token-usage benchmark: SAME task, gate OFF vs ON, per model, n reps.
# Opus + Sonnet via Claude Code (claude -p); gpt-5.5 via Codex worktree-accept.
# Gate ON now injects the grade-specific CONTRACT up front (one-pass spec) — this
# measures whether that removed the reactive-bounce overhead.
# Metric: gross tokens (input + cache_creation + cache_read + output) and $ cost.
# Rule: ratio gated/naked < 1.6 -> report in README; >= 1.6 -> exclude.
set +e
WFB="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS="$FORGE/adapters/hooks"
REPS="${REPS:-2}"
TASK="${BENCH_TASK:-Implement an LRUCache class in lru.py with get(key) and put(key, value) in O(1) using a dict plus a doubly linked list, a capacity set in the constructor, evicting the least-recently-used entry on overflow. get returns -1 on miss. Add test_lru.py with pytest cases for eviction, update-existing-key, and capacity 1. Stdlib only.}"
B=/tmp/tokbench2; rm -rf "$B"; mkdir -p "$B"; R="$B/results.txt"; : > "$R"

settings(){ mkdir -p "$1/.claude"; cat > "$1/.claude/settings.json" <<JSON
{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"python3 \"$HOOKS/user_prompt_submit.py\""}]}],"PreToolUse":[{"matcher":"Edit|Write|MultiEdit|NotebookEdit","hooks":[{"type":"command","command":"python3 \"$HOOKS/pre_tool_use.py\""}]}],"PostToolUse":[{"matcher":"Edit|Write|MultiEdit|NotebookEdit","hooks":[{"type":"command","command":"python3 \"$HOOKS/post_tool_use.py\""}]}],"Stop":[{"hooks":[{"type":"command","command":"python3 \"$HOOKS/stop.py\""}]}]}}
JSON
}
cg(){ python3 -c "import json,sys;u=json.load(open(sys.argv[1])).get('usage',{});print(u.get('input_tokens',0)+u.get('cache_creation_input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('output_tokens',0))" "$1" 2>/dev/null||echo 0; }
cc(){ python3 -c "import json,sys;print(round(json.load(open(sys.argv[1])).get('total_cost_usd',0),4))" "$1" 2>/dev/null||echo 0; }
built(){ [ -f "$1/lru.py" ] && echo Y || echo N; }   # guard: did the arm actually build?

claude_model(){ # $1 model  -> appends per-rep lines "<model> <rep> <naked_g> <gated_g> <ncost> <gcost> <nbuilt> <gbuilt>"
  local m="$1" i
  for i in $(seq 1 "$REPS"); do
    local N="$B/${m}_n${i}" G="$B/${m}_g${i}"
    mkdir -p "$N" "$G"; ( cd "$N" && git init -q ); ( cd "$G" && git init -q ); settings "$G"
    ( cd "$N" && timeout 600 claude -p "$TASK" --model "$m" --output-format json --dangerously-skip-permissions > out.json 2>/dev/null )
    ( cd "$G" && timeout 720 claude -p "$TASK" --model "$m" --output-format json --dangerously-skip-permissions > out.json 2>/dev/null )
    echo "$m $i $(cg "$N/out.json") $(cg "$G/out.json") $(cc "$N/out.json") $(cc "$G/out.json") $(built "$N") $(built "$G")" | tee -a "$R"
  done
}
codex_model(){ # gpt-5.5
  local i
  for i in $(seq 1 "$REPS"); do
    local N="$B/gpt_n${i}" REPO="$B/gpt_repo${i}"
    mkdir -p "$N"; ( cd "$N" && git init -q )
    ( cd "$N" && codex exec --json --skip-git-repo-check -s workspace-write -m gpt-5.5 -c model_reasoning_effort=medium "$TASK" < /dev/null > run.jsonl 2>/dev/null )
    mkdir -p "$REPO"; ( cd "$REPO" && git init -q && git config user.email t@t && git config user.name t && printf '#\n' > README.md && git add -A && git commit -qm base )
    ( WFB_KEEP=1 WFB_EFFORT=medium "$FORGE/adapters/codex/wfb-codex-accept.sh" "$TASK" --repo "$REPO" >/dev/null 2>&1 )
    WT=$(ls -dt "${TMPDIR:-/tmp}"/wfb-run-* /private/var/folders/*/*/T/wfb-run-* 2>/dev/null | head -1)
    gr(){ python3 "$FORGE/bench/sum_tokens.py" "$1" 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin)['raw_total'])" 2>/dev/null||echo 0; }
    local gb=N; [ -f "$WT/lru.py" ] && gb=Y
    echo "gpt-5.5 $i $(gr "$N/run.jsonl") $(gr "$WT/.wfb/codex_run.jsonl") - - $(built "$N") $gb" | tee -a "$R"
  done
}

echo "task: $TASK"; echo "reps=$REPS — gate ON = with up-front contract"
claude_model sonnet
claude_model opus
codex_model

echo; echo "=== RESULTS (gross tokens; ratio = mean gated / mean naked) ==="
python3 - "$R" <<'PY'
import sys,collections
# Per rep: model i naked_g gated_g ncost gcost nbuilt gbuilt
rows=collections.defaultdict(lambda:{'pairs':[]})
naked=collections.defaultdict(list)
for l in open(sys.argv[1]):
    p=l.split()
    if len(p)<8: continue
    m=p[0]; ng=int(p[2]); gg=int(p[3]); gb=p[7]
    naked[m].append(ng)
    rows[m]['pairs'].append((ng,gg,gb))
for m,r in rows.items():
    nmean=sum(naked[m])/len(naked[m])
    # A real gated run can NEVER use fewer gross tokens than naked (it does strictly
    # more: spec + verify on top of the same work). gated <= naked => the run was a
    # no-op / session-contaminated (claude -p resumed a stale finished session). Drop it.
    valid=[(ng,gg) for (ng,gg,gb) in r['pairs'] if gg>ng and gb=="Y"]
    dropped=len(r['pairs'])-len(valid)
    if not valid:
        print(f"{m:8s} NO VALID GATED REP (all dropped as no-op/contaminated)"); continue
    gmean=sum(gg for _,gg in valid)/len(valid)
    ratio=gmean/nmean if nmean else 0
    verdict="INCLUDE (<1.6x)" if 0<ratio<1.6 else "EXCLUDE (>=1.6x)"
    note=f"  (dropped {dropped} contaminated rep)" if dropped else ""
    print(f"{m:8s} naked~{nmean:>9.0f} gated~{gmean:>9.0f} ratio={ratio:.2f}x -> {verdict}  valid_g={[g for _,g in valid]}{note}")
PY
