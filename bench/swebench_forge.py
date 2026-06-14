#!/usr/bin/env python3
"""SWE-bench Verified slice: gate OFF (naked) vs ON (forge) on the SAME instances,
same model (opus). Generates a patch per arm with `claude -p`, scores with the official
swebench Docker harness. Run with the venv python that has swebench+datasets installed.

  /tmp/swe_venv/bin/python bench/swebench_forge.py --n 1            # smoke
  /tmp/swe_venv/bin/python bench/swebench_forge.py --ids a,b,c     # explicit

Honest expectation: the gate enforces process, not capability, so resolved-rate is
expected to be ~equal; this measures it rather than asserting it.
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

FORGE = Path("/Users/jeonsihyeon/fable-forge")
HOOKS = FORGE / "adapters/hooks"
GATE = FORGE / "gates/forge_gate.py"
WORK = Path("/tmp/swe"); WORK.mkdir(exist_ok=True)
DATASET = "princeton-nlp/SWE-bench_Verified"
LIGHT = ("psf/requests", "pallets/flask", "pytest-dev/pytest")

SETTINGS = {"hooks": {ev: [{"hooks": [{"type": "command", "command": f'python3 "{HOOKS}/{f}"'}]}]
                      for ev, f in [("UserPromptSubmit", "user_prompt_submit.py")]}}
SETTINGS["hooks"]["PreToolUse"] = [{"matcher": "Edit|Write|MultiEdit|NotebookEdit",
                                    "hooks": [{"type": "command", "command": f'python3 "{HOOKS}/pre_tool_use.py"'}]}]
SETTINGS["hooks"]["PostToolUse"] = [{"matcher": "Edit|Write|MultiEdit|NotebookEdit",
                                     "hooks": [{"type": "command", "command": f'python3 "{HOOKS}/post_tool_use.py"'}]}]
SETTINGS["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": f'python3 "{HOOKS}/stop.py"'}]}]

PROMPT = """Repository {repo} is checked out at the commit this issue refers to. A GitHub issue:

{problem}

Fix it by editing the repository's SOURCE files only. Do NOT modify tests or files under any tests/ directory — the grader supplies its own tests. Make the minimal change that resolves the issue. Your working-tree diff will be taken as the patch."""


def sh(cmd, cwd=None, timeout=None, env=None):
    return subprocess.run(cmd, cwd=cwd, timeout=timeout, env=env,
                          capture_output=True, text=True)


def clone(repo, base, dest):
    url = f"https://github.com/{repo}.git"
    sh(["git", "clone", "-q", url, str(dest)], timeout=600)
    sh(["git", "checkout", "-q", base], cwd=dest, timeout=120)


def gen_patch(repo, problem, dest, gated, model="opus"):
    """Run claude in dest, return (patch, tokens, cost, turns)."""
    if gated:
        (dest / ".claude").mkdir(exist_ok=True)
        (dest / ".claude" / "settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
        sh(["python3", str(GATE), "toggle", "--root", str(dest), "--scope", "project", "--set", "on"])
    out = sh(["claude", "-p", PROMPT.format(repo=repo, problem=problem[:6000]),
              "--model", model, "--output-format", "json", "--dangerously-skip-permissions"],
             cwd=dest, timeout=1800)
    tokens = cost = turns = 0
    try:
        j = json.loads(out.stdout)
        u = j.get("usage", {})
        tokens = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("output_tokens", 0)
        cost = j.get("total_cost_usd", 0); turns = j.get("num_turns", 0)
    except Exception:
        pass
    # stage everything except forge/claude artifacts, take the diff as the patch
    sh(["git", "add", "-A", "--", ".", ":!.forge", ":!.claude"], cwd=dest)
    patch = sh(["git", "diff", "--cached", "--", ".", ":!.forge", ":!.claude"], cwd=dest).stdout
    return patch, tokens, cost, turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--ids", default="")
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()

    from datasets import load_dataset
    ds = load_dataset(DATASET, split="test")
    by_id = {x["instance_id"]: x for x in ds}
    if a.ids:
        inst = [by_id[i] for i in a.ids.split(",")]
    else:
        # balanced round-robin across the light repos, simplest instances first
        per = {r: [] for r in LIGHT}
        for x in sorted(ds, key=lambda x: (len(json.loads(x["FAIL_TO_PASS"])), len(x["problem_statement"]))):
            if x["repo"] in per:
                per[x["repo"]].append(x)
        inst = []
        i = 0
        while len(inst) < a.n and any(i < len(per[r]) for r in LIGHT):
            for r in LIGHT:
                if i < len(per[r]) and len(inst) < a.n:
                    inst.append(per[r][i])
            i += 1

    preds = {"naked": [], "gated": []}
    meta = []
    for e in inst:
        iid, repo, base = e["instance_id"], e["repo"], e["base_commit"]
        print(f"\n=== {iid} ({repo}) ===", flush=True)
        for arm in ("naked", "gated"):
            d = WORK / f"{iid}__{arm}"
            if d.exists():
                sh(["rm", "-rf", str(d)])
            t0 = time.time()
            clone(repo, base, d)
            patch, tok, cost, turns = gen_patch(repo, e["problem_statement"], d, gated=(arm == "gated"), model=a.model)
            dt = time.time() - t0
            print(f"  {arm:6s} turns={turns} tokens={tok} cost=${cost:.3f} {dt:.0f}s patch={len(patch)}B", flush=True)
            preds[arm].append({"instance_id": iid, "model_name_or_path": f"forge_{arm}", "model_patch": patch})
            meta.append({"instance_id": iid, "arm": arm, "tokens": tok, "cost": cost, "turns": turns, "patch_bytes": len(patch), "secs": round(dt)})

    # merge with any existing preds/meta (so a slice can be grown without re-running it)
    for arm in ("naked", "gated"):
        p = WORK / f"preds_{arm}.jsonl"
        existing = {}
        if p.exists():
            for l in p.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l); existing[r["instance_id"]] = r
        for r in preds[arm]:
            existing[r["instance_id"]] = r
        p.write_text("\n".join(json.dumps(x) for x in existing.values()) + "\n", encoding="utf-8")
        print(f"wrote {p} ({len(existing)} total)")
    mp = WORK / "meta.json"
    allmeta = json.loads(mp.read_text()) if mp.exists() else []
    seen = {(m["instance_id"], m["arm"]) for m in meta}
    allmeta = [m for m in allmeta if (m["instance_id"], m["arm"]) not in seen] + meta
    mp.write_text(json.dumps(allmeta, indent=2), encoding="utf-8")
    print("\nINSTANCE_IDS=" + ",".join(e["instance_id"] for e in inst))


if __name__ == "__main__":
    main()
