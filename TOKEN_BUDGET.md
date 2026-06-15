# Token budget

Constraint (user): once the layer is absorbed into agent sessions, steady-state
token cost for the same task must stay **under 2× an Opus-naked baseline**.
During development, higher cost is fine.

This is a falsifiable number, so it is treated as an acceptance criterion to be
**measured**, not asserted. Below: where overhead comes from, the design that
keeps it small, and the measurement harness.

## Where wfb spends tokens

| Source | When | Steady-state size |
| --- | --- | --- |
| Procedure injection | once at task start (`additionalContext`) / cached `CLAUDE.md` | ~90 tok one-shot + ~300 tok cached (cache-read priced) |
| Spec output (`.wfb/spec.json`) | model writes it before coding | LIGHT ~150 · STANDARD ~600–1000 · HEAVY ~1500–2500 output tok |
| Gate block messages | only when the unmet-list changes (deduped) | ~200 tok × 1–2 blocks |
| Done-gate reminder | only on state change | ~100 tok |

The spec artifact and block messages are the *new content*, but they are **not** the
dominant cost — measurement (below) shows the gate's real expense is the extra
**turns** it forces (write spec → get blocked → implement → run acceptance → verify).
Each new turn re-processes the whole growing context, so the token total scales with
turn count, not with the size of the spec text. The table above is the per-item
content cost; the section below is the measured total.

## Measured: in-session (Claude Code), gate ON vs OFF

An earlier version of this doc *estimated* the in-session overhead at "+3–9%, far
under 2×". That estimate was wrong and is retracted — it counted only the spec
*output* (~1k tokens) and ignored that the gate makes the model take **more turns**
(write spec → get blocked → implement → run acceptance → verify), and in a
multi-turn agent each new turn re-bills the whole growing context. Now measured
directly (`bench/measure_tokens.sh`, headless `claude -p`, n=2, SAME task —
implement an LRU cache + tests, a small STANDARD task):

| model | turns OFF→ON | gross OFF→ON | gross ratio | $ ratio | real-token ratio* |
| --- | --- | --- | --- | --- | --- |
| sonnet | 5 → 11–16 | 135k → 403k | **2.99×** | 2.22× | **1.64×** |
| opus | 4–5 → 21 | 88k → 805k | **9.2×** | 5.57× | 3.34× |

*real-token = input + cache_creation + output, i.e. **excluding** `cache_read`.
~92% of the gross figure is `cache_read` — the same context re-read each extra turn,
billed at ~1/10 the input price. So the *cost* ratio (2.2× sonnet) is far below the
*gross-token* ratio (3.0×), and the genuinely-new tokens the gate adds are smaller
still (1.6× sonnet). Pick the metric honestly: by any of the three, a **small**
task is **over** the 2× target.

**Why a small task is the worst case.** The gate's cost is near-*fixed* (the spec
artifact + a verify turn or two ≈ +8k real tokens). Divided into a tiny naked
baseline (~12k) that is a big multiple; divided into a realistic 100k+ task it is
~1.1×. So the ratio falls as task size grows — but that larger-task ratio is **not
yet measured**, so it is not claimed here.

**What helped.** Injecting the full grade-specific pass-conditions up front (the
`contract` the hook now emits) cut sonnet's gross ratio from **4.53× → 2.99×** by
removing the reactive bounce (model discovering each required field by getting
blocked, each round re-billing context). It did not get a small task under 2×.

The token lever that keeps the *average* low is **grade-scaling**: LIGHT tasks
(typos, comments, renames) require only `restated_goal` + one acceptance check
(~150 tok); the full 8-axis spec is paid only on HEAVY (auth / payments / migration
/ security) — exactly where Fable itself escalates.

**The wrapper path does NOT meet 2× — measured.** `wfb-codex` runs SPEC /
IMPLEMENT / VERIFY as three `codex exec`/`resume` turns. Even single-session
(resume, ~86% cached), a measured run on one task (gpt-5.5, medium effort,
`bench/measure_overhead.sh`):

| arm | turns | raw_total | cache_adj |
| --- | --- | --- | --- |
| naked `codex exec` | 1 | 60,555 | 11,915 |
| wfbd `wfb-codex` | 3 | 862,522 | 132,282 |
| **ratio** | | **14.2×** | **11.1×** |

Both produced the same working output (slug.py + test). The 11× is the **3-pass
structure** — each agentic turn re-processes the cumulative context and runs its
own tool loop — **not** the spec content (the spec itself is ~2k tokens). So:

> The cost is the *mechanism* (3 separate agentic passes), not the *gate*.
> An in-session hook adds the spec to ONE pass; the wrapper multiplies passes.

The wrapper is therefore a **bootstrap / correctness** tool (use it where a hard
external gate is worth ~10×, e.g. high-stakes HEAVY tasks), **not** the
steady-state default. Bringing Codex under 2× requires one of:
- a **native Codex in-session hook** that blocks `apply_patch` until the gate
  passes (so enforcement lives inside one pass) — exists per
  `--dangerously-bypass-hook-trust` but its config/block schema is unconfirmed in
  0.139 (`adapters/codex/ENFORCEMENT.md` open question);
- a **lean 2-phase wrapper** where SPEC is a cheap no-exploration call and
  IMPLEMENT+VERIFY is one agentic pass (~1.5–2×, still tight).

## Measurement harness (the actual test of <2×)

Run the same fixed task set three ways and tally tokens:

```
arms:  naked        = model, no wfb
       wfbd       = model + wfb (in-session hook path, NOT the wrapper)
       reference    = the stronger reference model, naked   (quality anchor)

per task, per arm: total tokens (input+output), from
  - Codex:        `codex exec --json` emits per-turn token usage
  - Claude Code:  session transcript usage records

metric:   overhead = tokens(wfbd) / tokens(naked)
target:   mean(overhead) < 2.0   AND   p90(overhead) < 2.0
quality:  rubric/SCORECARD.md score(wfbd) should approach score(reference);
          that is the separate "does it lift the weaker model" question.
```

Token overhead and quality lift are **two different measurements** — keep them
separate. <2× is a cost gate; the quality lift is the 3-arm shadow benchmark.

## Status (measured)

- Grade-scaling implemented (`gates/wfb_gate.py`).
- **Claude Code in-session: measured, OVER 2× on a small task.** Native hooks fire
  (they are the live mechanism running this session), but the gate is **not** a
  single-pass additive term — it adds turns (spec → block → implement → verify), and
  each turn re-bills context. Measured (headless `claude -p`, n=2, small STANDARD
  LRU task): sonnet **2.99× gross / 2.22× cost / 1.64× real-tokens**, opus **9.2×
  gross / 5.6× cost**. The up-front `contract` cut sonnet from 4.53× → 2.99×. Small
  tasks are the worst case (fixed gate cost ÷ tiny baseline); the amortized
  large-task ratio is plausibly near 1× but is **unmeasured, so not claimed**.
- **Codex wrapper: measured 11–14×** — the cost is the 3-pass structure, not the
  gate. It is the *confirmed* headless Codex path, but it is expensive (bootstrap /
  high-stakes only).
- **Codex native-hook in-session: NOT confirmed.** Three real `codex exec` runs
  failed to gate: (a) `codex exec` does not fire `UserPromptSubmit` (no
  auto-scaffold); (b) even with a pre-scaffold and `--dangerously-bypass-hook-trust`,
  a trivial PreToolUse test hook **never ran** and the edit went through. The
  numbers from those runs are gpt-5.5 run-to-run variance, not gating. So Codex's
  in-session <2× path is plausible (the hook scripts work in isolation) but
  **unproven in headless exec** — likely needs interactive `/hooks` trust or a
  different hook location/enable. Open item.
- **Codex worktree-accept (the shipped headless path): measured ~5× raw / ~1.4–4×
  cache_adj** on a STANDARD task vs a naked baseline (gpt-5.5, one pass) — **over 2×.**
  It is ONE codex pass (not the wrapper's 3), but the gated worker genuinely *does
  more*: it writes a full spec (3 non_goals, 3 rejected_alternatives, risks) **and
  runs real verification** (pytest + py_compile + import, capturing live evidence)
  that the naked baseline skips entirely.
- **Honest correction on <2×:** my earlier "+3%" was wrong — it counted only the
  spec *output* (~1–2k) and ignored that producing the spec and **running the
  acceptance commands** adds tool-calls and context. The token overhead is
  dominated by *doing the process*, not by the wrapper structure. So:
  - **LIGHT tasks: expected <2× but not separately measured** — grade-scaling keeps them
    to restated_goal + one acceptance check (~150 tok), so the fixed overhead is tiny;
    the measured runs above are STANDARD, so treat LIGHT as a (reasoned) expectation only.
  - **STANDARD/HEAVY: honestly over 2×** against a *lazy* naked baseline — but much
    of the delta is verification work you'd want regardless. Against a *thorough*
    naked (one told to spec + test properly), the pure gate overhead is small.
- **Net, honest:** total enforcement is achieved on both runtimes (CC in-session
  hooks; Codex worktree-accept). The **<2× cost target is missed for STANDARD+**
  (measured 2–9× gross / 2.2–5.6× cost on a small task) and **only expected — not
  measured — to hold for LIGHT** (grade-scaling keeps it to restated_goal + one check).
  Enforcing the full Fable process is real extra work, not free. The "+3%",
  "wrapper ≈ 2–3×", "Codex native hook = primary", and "in-session ~<2×" claims were
  all wrong; measurement corrected each.
