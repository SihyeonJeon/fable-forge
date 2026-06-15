#!/usr/bin/env bash
# Quality benchmark: gate/layer ON (wfbd) vs OFF (naked), SAME tasks, scored by a
# HIDDEN grader (edge cases the model never sees). Measures whether forcing the
# spec+verify discipline lifts a weaker model's (gpt-5.5) output correctness.
# ~6 codex runs. set WFB_EFFORT (default medium).
set +e
FORGE="$(cd "$(dirname "$0")/.." && pwd)"
Q="$FORGE/bench/quality"
GRADE="python3 $Q/grade.py"
MODEL="${WFB_MODEL:-gpt-5.5}"; EFFORT="${WFB_EFFORT:-medium}"
B="${TMPDIR:-/tmp}/qbench"; rm -rf "$B"; mkdir -p "$B"
CX=(--json --skip-git-repo-check -s workspace-write -m "$MODEL" -c model_reasoning_effort="$EFFORT")

# task: id | file | symbol | seedfile(optional) | prompt
TASKS=(
"A|slug.py|slugify||Write slugify(s) in slug.py: lowercase the string, replace runs of non-alphanumeric characters with a single hyphen, and strip leading/trailing hyphens. Empty or all-symbol input returns an empty string. Stdlib only."
"B|dur.py|parse_duration||Write parse_duration(s) in dur.py that parses duration strings like '1h30m', '45s', '2h', '90m', '1h1m1s' into total seconds as an int. Raise ValueError on invalid input. Stdlib only."
"C|primes.py|is_prime|$Q/seed_primes.py|Optimize the is_prime(n) function in primes.py for speed. It MUST keep exactly the same result for every integer, including n<2 and negatives (not prime) and 2/3 (prime). Stdlib only."
)

run_naked(){ # id file seed prompt -> echoes module path
  local id="$1" file="$2" seed="$3" prompt="$4" D="$B/naked_$1"
  mkdir -p "$D"; ( cd "$D" && git init -q ) >/dev/null 2>&1
  [ -n "$seed" ] && cp "$seed" "$D/$file"
  ( cd "$D" && codex exec "${CX[@]}" "$prompt" < /dev/null > run.jsonl 2>/dev/null )
  echo "$D/$file"
}

run_wfbd(){ # id file seed prompt -> echoes module path + sets GATE_OUT
  local id="$1" file="$2" seed="$3" prompt="$4" R="$B/wfbd_$1"
  mkdir -p "$R"; ( cd "$R" && git init -q && git config user.email t@t && git config user.name t ) >/dev/null 2>&1
  [ -n "$seed" ] && cp "$seed" "$R/$file"
  printf '# bench\n' > "$R/README.md"
  ( cd "$R" && git add -A && git commit -qm base ) >/dev/null 2>&1
  local err
  err="$(cd "$R" && WFB_KEEP=1 WFB_EFFORT="$EFFORT" WFB_MODEL="$MODEL" "$FORGE/adapters/codex/wfb-codex-accept.sh" "$prompt" --repo "$R" 2>&1 >/tmp/qf_out.$id)"
  GATE_OUT="$(grep -oE 'ACCEPTED|REJECTED' /tmp/qf_out.$id | head -1)"
  local WT; WT="$(printf '%s\n' "$err" | sed -n 's/.*worktree kept at //p' | head -1)"
  if [ -f "$R/$file" ]; then echo "$R/$file"; else echo "$WT/$file"; fi
}

echo "=== Quality benchmark (gpt-5.5, effort=$EFFORT) — hidden-grader pass rate ==="
printf "%-4s %-16s  %-14s  %-14s  %s\n" "task" "symbol" "naked" "wfbd(gate)" "gate"
declare -a SUMMARY
for row in "${TASKS[@]}"; do
  IFS='|' read -r id file sym seed prompt <<< "$row"
  nf="$(run_naked  "$id" "$file" "$seed" "$prompt")"
  ff="$(run_wfbd "$id" "$file" "$seed" "$prompt")"
  ns="$($GRADE "$nf" "$id" 2>/dev/null)"; [ -z "$ns" ] && ns="0 ?"
  fs="$($GRADE "$ff" "$id" 2>/dev/null)"; [ -z "$fs" ] && fs="0 ?"
  printf "%-4s %-16s  %-14s  %-14s  %s\n" "$id" "$sym" "$ns" "$fs" "${GATE_OUT:-?}"
  SUMMARY+=("$id naked=$ns wfbd=$fs gate=${GATE_OUT:-?}")
done
echo; echo "=== summary ==="; printf '%s\n' "${SUMMARY[@]}"
echo "(score = hidden edge-case assertions passed / total)"
