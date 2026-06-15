#!/usr/bin/env python3
"""SWE-bench Pro slice: gate OFF (naked) vs ON (wfb), same model (opus).
Clones the real repo at base_commit, generates a patch per arm with `claude -p`, writes
a CSV + patches JSON for the ScaleAI SWE-bench Pro harness. Run with the venv python.

  /tmp/swe_venv/bin/python bench/swebenchpro_wfb.py --ids <id1,id2>
"""
import argparse, json, subprocess, time
from pathlib import Path
import pandas as pd
from datasets import load_dataset

FORGE = Path("/Users/jeonsihyeon/wfb")
HOOKS = FORGE / "adapters/hooks"
GATE = FORGE / "gates/wfb_gate.py"
WORK = Path("/tmp/swepro"); WORK.mkdir(exist_ok=True)

SETTINGS = {"hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": f'python3 "{HOOKS}/user_prompt_submit.py"'}]}],
    "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": f'python3 "{HOOKS}/pre_tool_use.py"'}]}],
    "PostToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": f'python3 "{HOOKS}/post_tool_use.py"'}]}],
    "Stop": [{"hooks": [{"type": "command", "command": f'python3 "{HOOKS}/stop.py"'}]}]}}

PROMPT = """Repository {repo} is checked out at the commit this issue refers to. A GitHub issue:

{problem}

Fix it by editing the repository's SOURCE files only. Do NOT modify tests or files under any tests/ directory — the grader supplies its own tests. Make the minimal change that resolves the issue. Your working-tree diff will be taken as the patch."""


def sh(cmd, cwd=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True)


def gen_patch(repo, problem, dest, gated, model="opus"):
    url = f"https://github.com/{repo}.git"
    sh(["git", "clone", "-q", url, str(dest)], timeout=900)
    base = None  # caller checks out
    return dest


def make_patch(repo, problem, dest, base, gated, model="opus"):
    url = f"https://github.com/{repo}.git"
    sh(["git", "clone", "-q", url, str(dest)], timeout=1200)
    sh(["git", "checkout", "-q", base], cwd=dest, timeout=180)
    if gated:
        (dest / ".claude").mkdir(exist_ok=True)
        (dest / ".claude" / "settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
        sh(["python3", str(GATE), "toggle", "--root", str(dest), "--scope", "project", "--set", "on"])
    out = sh(["claude", "-p", PROMPT.format(repo=repo, problem=problem[:7000]),
              "--model", model, "--output-format", "json", "--dangerously-skip-permissions"],
             cwd=dest, timeout=2400)
    tok = cost = turns = 0
    try:
        j = json.loads(out.stdout); u = j.get("usage", {})
        tok = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("output_tokens", 0)
        cost = j.get("total_cost_usd", 0); turns = j.get("num_turns", 0)
    except Exception:
        pass
    sh(["git", "add", "-A", "--", ".", ":!.wfb", ":!.claude"], cwd=dest)
    patch = sh(["git", "diff", "--cached", "--", ".", ":!.wfb", ":!.claude"], cwd=dest).stdout
    return patch, tok, cost, turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()
    ds = load_dataset("ScaleAI/SWE-bench_Pro", split="test")
    by = {x["instance_id"]: x for x in ds}
    inst = [by[i] for i in a.ids.split(",")]

    # CSV for the Pro harness (merge with existing so the slice can grow)
    cols = ["instance_id", "repo", "base_commit", "before_repo_set_cmd",
            "selected_test_files_to_run", "fail_to_pass", "pass_to_pass", "dockerhub_tag"]
    csv_path = WORK / "samples.csv"
    rows = {r["instance_id"]: r for r in (json.loads((WORK / "samples.json").read_text()) if (WORK / "samples.json").exists() else [])}
    for e in inst:
        rows[e["instance_id"]] = {c: e[c] for c in cols}
    (WORK / "samples.json").write_text(json.dumps(list(rows.values())))
    pd.DataFrame(list(rows.values()))[cols].to_csv(csv_path, index=False)

    preds = {"naked": {}, "gated": {}}
    for arm in ("naked", "gated"):
        pf = WORK / f"patches_{arm}.json"
        if pf.exists():
            preds[arm] = {p["instance_id"]: p for p in json.loads(pf.read_text())}
    meta = json.loads((WORK / "meta.json").read_text()) if (WORK / "meta.json").exists() else []

    for e in inst:
        iid, repo, base = e["instance_id"], e["repo"], e["base_commit"]
        print(f"\n=== {iid} ({repo}) ===", flush=True)
        for arm in ("naked", "gated"):
            d = WORK / f"{iid[:40]}__{arm}"
            if d.exists():
                sh(["rm", "-rf", str(d)])
            t0 = time.time()
            patch, tok, cost, turns = make_patch(repo, e["problem_statement"], d, base, gated=(arm == "gated"), model=a.model)
            dt = time.time() - t0
            print(f"  {arm:6s} turns={turns} tokens={tok} cost=${cost:.3f} {dt:.0f}s patch={len(patch)}B", flush=True)
            preds[arm][iid] = {"instance_id": iid, "patch": patch, "prefix": f"wfb_{arm}"}
            meta = [m for m in meta if not (m["instance_id"] == iid and m["arm"] == arm)]
            meta.append({"instance_id": iid, "arm": arm, "tokens": tok, "cost": cost, "turns": turns, "secs": round(dt)})
            sh(["rm", "-rf", str(d)])  # free disk between arms

    for arm in ("naked", "gated"):
        (WORK / f"patches_{arm}.json").write_text(json.dumps(list(preds[arm].values()), indent=2))
    (WORK / "meta.json").write_text(json.dumps(meta, indent=2))
    print("\nCSV:", csv_path, "| patches written |", len(rows), "instances total")


if __name__ == "__main__":
    main()
