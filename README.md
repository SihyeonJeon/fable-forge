# why-was-fable-banned

**English** · [한국어](README.ko.md)

> Gate for AI coding agents: blocks edits until a spec passes.

![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3-3776AB?logo=python&logoColor=white)
![Claude Code](https://img.shields.io/badge/Claude%20Code-native%20hooks-d97757)
![Codex](https://img.shields.io/badge/Codex-worktree--accept-10a37f)
[![tests](https://github.com/SihyeonJeon/why-was-fable-banned/actions/workflows/ci.yml/badge.svg)](https://github.com/SihyeonJeon/why-was-fable-banned/actions/workflows/ci.yml)

![why-was-fable-banned](assets/social-preview.jpg)

The agent can't edit code until it writes `.forge/spec.json` and a deterministic
gate accepts it: restated goal, non-goals, context chosen by authority, ≥2 rejected
alternatives with the boundary each breaks, risks, and runnable acceptance. One
shared gate, installed as hooks. Works in **Claude Code** and **Codex**.

![demo: edit blocked until the spec passes, then applied](assets/demo.gif)

> [!NOTE]
> A spec must exist and pass before edits land, and unspeced or forbidden-path work
> never reaches your repo. Every change ships with an auditable decision record.

## Install

```sh
git clone https://github.com/SihyeonJeon/why-was-fable-banned
cd why-was-fable-banned && sh install.sh
```

`python3` only, stdlib. Remove: `sh install.sh --uninstall`.

## Scope

- `sh install.sh` — **machine-wide**: every Claude Code project on this computer (and every subagent / orchestrated worker) inherits the gate
- `sh install.sh --here` — **this repo only** (Claude Code project-level `.claude/settings.json`)
- `forge off` / `forge on` / `forge status` — toggle in-session; handled by the hook, never sent to the model. It flips a per-**project** flag (`.forge/OFF`), so it persists across sessions in that repo until you flip it back
- **Works wherever Claude Code runs** — terminal, the VS Code and JetBrains extensions, desktop (they share the same hooks) — plus Codex. It does not apply to non-Claude-Code/Codex agents (e.g. Cursor's own agent)

## How it works

- **Block**: a `PreToolUse` hook intercepts every edit and exits 2 until the spec passes
- **Spec**: restated goal · non-goals · context by authority · ≥2 rejected alternatives · risks · runnable acceptance · forbidden paths
- **Verify**: "done" isn't done until each acceptance command shows live output (fail closed)
- **Apply**: on headless Codex the worker runs in a throwaway git worktree; only a gate-passing diff reaches your repo

## Quickstart

1. `sh install.sh`: wires the hooks at user level (every project + subagent inherits it)
2. Prompt your agent to do real work: a gated task auto-starts
3. The agent writes `.forge/spec.json` (it's told exactly what to fill); edits stay blocked until it passes
4. It implements, runs the acceptance commands, records evidence, then closes

Grade auto-scales the depth: typos pay almost nothing, auth/payments/migration pay
the full gate.

## Supported agents

- **Claude Code**: native hooks, in-session block (the spec adds to one pass)
- **Codex**: `forge-codex-accept "<goal>" --repo <dir>` (worktree-accept; headless)

## Where the rules came from

Recorded real engineering sessions with hooks (42 traces), extracted them as a
structured decision schema, generalized 19 into 8 decision axes, and cross-checked
the generalization with a second model. Observable artifacts only: no
chain-of-thought, local, secrets masked.

<details>
<summary>Three layers, increasing cost and depth</summary>

| layer | checks | how |
| --- | --- | --- |
| `gates/forge_gate.py` | **form**: fields, real paths, forbidden, fail-closed | deterministic, free |
| `gates/forge_judge.py` | **meaning**: 0–2 rubric, gaming detection | optional LLM judge |
| `bench/` | **correctness**: hidden grader | runs the tests |

</details>

## Benchmarks

Measured in this repo, reproducible (`bash bench/run_quality.sh`, `bash tests/run_all.sh`):

| measure | gate OFF | gate ON |
| --- | --- | --- |
| Decision record per change | none | **enforced** |
| Unspeced or forbidden-path edits reaching the repo | possible | **blocked** |
| Token overhead, in-session (Claude Code) | 1× | ~+spec; LIGHT under 2× |
| Adversarial / edge gate tests (downgrade, bypass, malformed, no-brick) | n/a | **35/35 pass** |

Validated live: a Codex run left a protected file untouched and applied only the
gate-passing diff; if verification is incomplete it retries, then rejects rather than
apply. Details: [bench/BENCHMARK.md](bench/BENCHMARK.md) · [TOKEN_BUDGET.md](TOKEN_BUDGET.md).

## License

PRs welcome. MIT.
