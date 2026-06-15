#!/usr/bin/env python3
"""fable-forge gate engine — self-contained, stdlib only, model-agnostic.

Enforces the SPEC -> IMPLEMENT -> VERIFY procedure by validating a lightweight
spec artifact (`.forge/spec.json`) under the project root. Runtime adapters
(Claude Code hooks, Codex execpolicy/wrapper) call this and block on a non-zero
exit. No dependency on fable-pack; nothing networked; secrets never read.

Subcommands:
  scaffold  --root R --goal G [--grade L]   create .forge/, ACTIVE marker, spec skeleton
  validate  --root R --gate spec|done       exit 0 pass / 1 fail; prints failures
  active    --root R                         exit 0 if a task is active, else 1
  status    --root R                         human-readable state
  close     --root R                         clear ACTIVE (after done gate passes)
  classify  --text T                         exit 0 if prompt is work-shaped, else 1
  contract  --root R                          print the grade's full pass-conditions (inject up front)
  toggle    --root R --scope S --set on|off    turn the gate on/off at session|project|machine scope
  state     --root R [--sid ID] [--verbose]    print effective on/off (most-specific scope wins)

Exit codes: 0 = pass/yes, 1 = fail/no, 2 = usage/internal error.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path

FORGE_DIR = ".forge"
SPEC_NAME = "spec.json"
ACTIVE_NAME = "ACTIVE"

ALT_CATEGORIES = {"tempting_shortcut", "architecture", "scope", "compatibility"}
# A "risk" that normalizes to one of these is a non-declaration — rejected so the
# STANDARD+ risk requirement can't be satisfied with a placeholder.
NO_RISK_PLACEHOLDERS = {"none", "n/a", "na", "no risk", "no risks", "nothing", "no"}
SEVERITIES = {"low", "medium", "high", "blocking"}
ACC_TYPES = {"command", "grep", "stat", "artifact", "human_visual", "test"}
# Evidence that is really a non-run admission — the honesty invariant, enforced.
FAKE_MARKERS = ("not run", "notrun", "did not run", "didn't run", "assumed",
                "would pass", "should pass", "to be done", "tbd", "todo",
                "n/a", "pending", "placeholder", "will run", "not yet")

SPEC_TEMPLATE = {
    "grade": "STANDARD",
    "phase": "SPEC",
    "raw_goal": "",
    "restated_goal": "",
    "non_goals": [],
    "ambiguities": [],              # {question, resolution, authority}
    "must_read": [],                # {path, authority_reason}
    "similar_implementations": [],  # {path, symbol, why}  (HEAVY: mirror to avoid breaking an invariant)
    "constraints": {"architectural": [], "invariant": [], "convention": []},  # arch: {constraint, evidence_ref}
    "rejected_alternatives": [],    # {category, alternative, broken_boundary}
    "risks": [],                    # {risk, severity, mitigation, acceptance_ref}
    "observations": [],             # {observation, changed_understanding(bool), evidence_ref}  (validation loop)
    "deferred": [],                 # tracked backlog / abandoned-but-recorded paths
    "forbidden_paths": [],          # globs the change must NOT touch (architecture/policy); verified at done
    "acceptance_criteria": [],      # {criterion, verify:{type,value}, evidence}
}

# Work-shaped prompt heuristic (English + Korean). Questions / chatter do not gate.
WORK_RE = re.compile(
    r"\b(implement|fix|refactor|add|build|create|write|change|update|migrat\w*|"
    r"remove|delete|rename|optimi\w*|debug|patch|integrat\w*|wire|hook up|set up)\b",
    re.I,
)
WORK_KO = ("구현", "수정", "고쳐", "고치", "추가", "만들", "리팩", "변경", "바꿔",
           "바꾸", "삭제", "지워", "통합", "연결", "배선", "최적화", "패치")
QUESTION_KO_ENDINGS = ("나요", "까요", "가요", "은가", "는가", "ㄴ가", "?", "？")
HEAVY_RE = re.compile(
    r"\b(auth|authn|authz|authenticat\w*|authoriz\w*|authoris\w*|oauth|openid|sso|jwt|"
    r"payment\w*|migrat\w*|schema|backfill|security|crypto|password\w*|secrets?|"
    r"credential\w*|billing|permission\w*|destructive|distributed|cross.?process|"
    r"deadlock|vulnerab\w*|exploit|xss|ssrf|csrf|sanitiz\w*|sanitis\w*|sql\s+injection)\b"
    r"|\b(?:drop|delete|truncate|purge)\s+(?:the\s+|all\s+|old\s+|stale\s+)*"
    r"(?:records?|rows?|users?|data|accounts?|tables?)\b", re.I)
HEAVY_KO = ("보안", "결제", "인증", "마이그", "비밀번호", "권한", "과금", "스키마", "분산")
# Real engineering difficulty/risk that needs the STANDARD decision spec even with no
# HEAVY keyword (concurrency, correctness-critical, algorithmic).
STANDARD_RE = re.compile(
    r"\b(race|lock(?:ing|ed|s)?|thread\w*|async\w*|asynchron\w*|concurren\w*|atomic|"
    r"scheduler|cache|eviction|planner|parser|algorithm\w*|invariant|correctness|"
    r"optimi\w*|performance|state[-\s]?machine|retry|idempoten\w*)\b", re.I)
STANDARD_KO = ("동시성", "락", "스레드", "비동기", "경쟁", "캐시", "알고리즘", "불변", "성능", "정확성")
# Strong non-trivial verbs (building/reshaping real behaviour => STANDARD). Ambiguous
# noun-verbs (build/create/design) are NOT here — they fall to the default and let an
# explicit LIGHT keyword win (e.g. "fix wording on Create button").
NONTRIVIAL_VERB_RE = re.compile(r"\b(implement\w*|rewrite|refactor\w*|integrat\w*|"
                                r"optimi\w*|redesign)\b", re.I)


def spec_path(root: Path) -> Path:
    return root / FORGE_DIR / SPEC_NAME


def active_path(root: Path) -> Path:
    return root / FORGE_DIR / ACTIVE_NAME


# ----------------------------------------------------------- on/off state ----
# The gate can be turned on/off at three scopes; the most specific set wins:
#   session  (this conversation)      ->  <root>/.forge/sessions/<session_id>
#   project  (this repo dir)          ->  <root>/.forge/STATE   (legacy: .forge/OFF)
#   machine  (whole desktop)          ->  ~/.forge/STATE  (override dir: $FORGE_HOME)
# Each STATE file holds "on" or "off"; absence = inherit the next scope; default ON.
SCOPES = ("session", "project", "machine")


def _machine_dir() -> Path:
    # Must NOT be any project's <root>/.forge — else a Claude project opened at $HOME
    # would make `forge off` (project) collide with machine state. Use the XDG config dir.
    if os.environ.get("FORGE_HOME"):
        return Path(os.environ["FORGE_HOME"])
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "forge"


def _read_state(p: Path):
    try:
        if p.exists():
            v = p.read_text(encoding="utf-8").strip().lower()
            if v in ("on", "off"):
                return v
    except Exception:
        pass
    return None


def _safe_sid(sid) -> str:
    # sid is an arbitrary runtime string — never use it as a path directly (/, .., abs
    # would escape the sessions dir). Hash to a fixed, collision-resistant, escape-proof
    # filename component (a plain char-strip would collide, e.g. "a/b" vs "a_b").
    return hashlib.sha256(str(sid).encode("utf-8", "replace")).hexdigest()[:32]


def _session_state_path(root, sid) -> Path:
    return Path(root) / FORGE_DIR / "sessions" / _safe_sid(sid)


def _scope_states(root, sid):
    """(session, project, machine) raw state, each 'on' / 'off' / None (inherit)."""
    sess = _read_state(_session_state_path(root, sid)) if sid else None
    proj = _read_state(Path(root) / FORGE_DIR / "STATE")
    if proj is None and (Path(root) / FORGE_DIR / "OFF").exists():
        proj = "off"  # back-compat with the old binary OFF marker
    mach = _read_state(_machine_dir() / "STATE")
    return sess, proj, mach


def effective_state(root, sid=None) -> str:
    """Resolve on/off by precedence: session > project > machine > default ON."""
    sess, proj, mach = _scope_states(root, sid)
    for s in (sess, proj, mach):
        if s:
            return s
    return "on"


def load_spec(root: Path):
    p = spec_path(root)
    if not p.exists():
        return None, f"no spec at {p}"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # malformed JSON must read as a gate failure, not crash
        return None, f"spec.json is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "spec.json must be a JSON object"
    return data, None


def _nonempty(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _inv_text(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return x.get("invariant") or x.get("text") or ""
    return ""


def _is_placeholder_risk(text) -> bool:
    """True if a 'risk' is really a non-declaration ('none', 'N/A.', 'No risks!', ...).
    Strip all non-alphanumerics so trailing punctuation/spacing can't smuggle one past."""
    core = re.sub(r"[^a-z0-9]", "", _norm(text))
    return core in {re.sub(r"[^a-z0-9]", "", p) for p in NO_RISK_PLACEHOLDERS}


def _forbidden_hits(spec: dict, root) -> list:
    """Edits (recorded by the PostToolUse hook in .forge/edits.txt) that match a
    forbidden_paths glob — i.e. the implementation touched an architecture/policy
    boundary the spec declared off-limits. Verifies no-conflict, not just declares."""
    pats = [p for p in spec.get("forbidden_paths", []) if isinstance(p, str) and p.strip()]
    if not pats or root is None:
        return []
    log = Path(root) / FORGE_DIR / "edits.txt"
    if not log.exists():
        return []
    try:
        edited = [ln.strip() for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return []
    rootres = str(Path(root).resolve())
    hits = []
    for ed in edited:
        # Canonical, root-relative form so an absolute log entry or a symlink alias can't
        # edit a forbidden file without matching its forbidden_paths glob.
        try:
            ap = ed if os.path.isabs(ed) else os.path.join(rootres, ed)
            rel = os.path.relpath(os.path.realpath(ap), rootres)
        except Exception:
            rel = ed
        for pat in pats:
            key = pat.strip("*/ ")
            if (fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(ed, pat)
                    or (key and (key in rel or key in ed))):
                hits.append((ed, pat))
                break
    return hits


GRADE_RANK = {"LIGHT": 0, "STANDARD": 1, "HEAVY": 2}


def _canon_edit(p, root) -> str:
    """Canonical absolute path for a logged/pending edit target, so 'a.py', './a.py'
    and '/root/a.py' collapse to one entry (no false multi-file counts)."""
    try:
        pp = Path(p)
        if not pp.is_absolute():
            pp = Path(root) / pp
        return str(pp.resolve())
    except Exception:
        return str(p)


def _edited_files(root, pending=None) -> set:
    """Distinct, canonicalized, non-.forge files touched so far (from edits.txt) plus any
    `pending` targets of the edit currently being evaluated — so escalation is decided
    BEFORE the spreading edit is authorized, not backfilled afterwards."""
    if root is None:
        return set()
    forge = str((Path(root) / FORGE_DIR).resolve())
    out = set()
    raw = []
    log = Path(root) / FORGE_DIR / "edits.txt"
    if log.exists():
        try:
            raw += [ln.strip() for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except Exception:
            pass
    raw += [str(p).strip() for p in (pending or []) if str(p).strip()]
    for ln in raw:
        c = _canon_edit(ln, root)
        if c == forge or c.startswith(forge + os.sep):
            continue  # never count .forge/ self-authoring
        out.add(c)
    return out


def _edited_file_count(root, pending=None) -> int:
    return len(_edited_files(root, pending))


def _good_acceptance(spec) -> int:
    return len([c for c in spec.get("acceptance_criteria", [])
                if isinstance(c, dict) and _nonempty((c.get("verify") or {}).get("value"))])


def _spec_lock_path(root) -> Path:
    return Path(root) / FORGE_DIR / "spec.lock"


def _acc_identity(spec: dict) -> set:
    """Identity of each runnable acceptance check ('type|normalized-command') — so a check
    can't be swapped for a weaker command while keeping the count."""
    out = set()
    for c in spec.get("acceptance_criteria", []):
        if isinstance(c, dict):
            v = c.get("verify") or {}
            if _nonempty(v.get("value")):
                out.add(f"{(v.get('type') or '').strip().lower()}|{_norm(v.get('value'))}")
    return out


def _write_spec_lock(spec: dict, root) -> None:
    """Each time the SPEC gate passes, MONOTONICALLY merge the approved promises into the
    lock (union of forbidden_paths + acceptance identities). The model can STRENGTHEN the
    spec (add forbidden / checks / evidence) but can never WEAKEN it to pass done against a
    softer spec — even across a LIGHT->STANDARD escalation re-approval."""
    if root is None:
        return
    p = _spec_lock_path(root)
    prev = {"forbidden_paths": [], "acceptance": []}
    if p.exists():
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            prev = {"forbidden_paths": [], "acceptance": []}
    forbidden = sorted(set(prev.get("forbidden_paths", [])) |
                       {x for x in spec.get("forbidden_paths", []) if isinstance(x, str) and x.strip()})
    acc = sorted(set(prev.get("acceptance", [])) | _acc_identity(spec))
    try:
        p.write_text(json.dumps({"forbidden_paths": forbidden, "acceptance": acc}), encoding="utf-8")
    except Exception:
        pass


def _spec_weakened(spec: dict, root) -> list:
    """In-session weakening guard: a spec.lock (written when the spec was approved) must not
    lose any forbidden_path or any approved acceptance check. (No lock => nothing to compare;
    the worktree-accept path, where the worker is unrestricted, relies on its diff check, not
    this — see adapters/codex/ENFORCEMENT.md.)"""
    if root is None:
        return []
    p = _spec_lock_path(root)
    if not p.exists():
        return []
    try:
        lock = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    e = []
    cur_f = {x for x in spec.get("forbidden_paths", []) if isinstance(x, str) and x.strip()}
    removed = [x for x in lock.get("forbidden_paths", []) if x not in cur_f]
    if removed:
        e.append(f"forbidden_paths weakened after approval (removed {removed}) — the spec is "
                 "frozen against weakening; restore them or justify each removal.")
    cur_a = _acc_identity(spec)
    gone = [a for a in lock.get("acceptance", []) if a not in cur_a]
    if gone:
        e.append(f"{len(gone)} approved acceptance check(s) were removed or altered after "
                 "approval — add evidence to the approved checks instead of changing them.")
    return e


# Match path SEGMENTS / filenames (not unbounded substrings) on the ROOT-RELATIVE path, so
# a repo dir like 'payment-app/' or a file like 'immigration_notes.md' / 'passwordless.css'
# doesn't make every edit HEAVY, while real auth/migration/secret files do.
HEAVY_PATH_RE = re.compile(
    r"(^|/)(migrations?|auth|authn|authz|authenticat\w*|authoriz\w*|oauth|sso|jwt|security|"
    r"secrets?|credentials?|sessions?|billing|payments?|permissions?|schema)([/._]|$)"
    r"|(^|/)tokens?([/.]|$)"                                   # token(s) as a full segment/file
    r"|(?:access|refresh|auth|api|bearer|csrf|id|session)[-_]tokens?"  # credential-shaped token
    r"|\.sql(\.\w+)?$", re.I)


def _touches_heavy_path(root, pending=None) -> bool:
    """A change that actually touches an auth/migration/schema/secret file earns HEAVY at
    runtime regardless of the prompt wording. Matched on root-relative POSIX paths."""
    try:
        rootres = str(Path(root).resolve()) if root is not None else ""
    except Exception:
        rootres = ""
    for f in _edited_files(root, pending):
        rel = os.path.relpath(f, rootres) if rootres else f
        rel = rel.replace(os.sep, "/")
        if HEAVY_PATH_RE.search(rel):
            return True
    return False


def _effective_grade(spec: dict, root, pending=None) -> str:
    """Grade drives enforcement depth. Base is the scaffold-written `.forge/GRADE`
    (authoritative — a model cannot downgrade in spec.json to skip checks). It is then
    escalated UP (never down) by RUNTIME signals: a change that spreads across >=2 files
    is no longer trivial, so a LIGHT task earns the STANDARD decision spec. This is the
    dynamic lever — simple one-file fixes stay LIGHT (cheap), spreading changes pay more."""
    base = None
    if root is not None:
        gf = Path(root) / FORGE_DIR / "GRADE"
        if gf.exists():
            try:
                g = gf.read_text(encoding="utf-8").strip().upper()
                if g in GRADE_RANK:
                    base = g
            except Exception:
                pass
    if base is None:
        # No valid GRADE lock. If a task is ACTIVE, the lock was tampered/lost — fail
        # closed at HEAVY (the strictest), since the original could have been HEAVY and we
        # must not silently downgrade a lost lock.
        if root is not None and (Path(root) / FORGE_DIR / ACTIVE_NAME).exists():
            base = "HEAVY"
        else:
            base = (spec.get("grade") or "LIGHT").upper()
            if base not in GRADE_RANK:
                base = "LIGHT"
    rank = GRADE_RANK[base]
    if _edited_file_count(root, pending) >= 2:
        rank = max(rank, GRADE_RANK["STANDARD"])  # multi-file (incl. pending) => >= STANDARD
    if _touches_heavy_path(root, pending):
        rank = max(rank, GRADE_RANK["HEAVY"])      # auth/migration/schema/secret => HEAVY
    return next(g for g, r in GRADE_RANK.items() if r == rank)


# ---------------------------------------------------------------- spec gate ---
def gate_spec(spec: dict, root=None, pending=None) -> list[str]:
    """Grade-tiered. LIGHT pays almost nothing (token lever); STANDARD adds the
    core decision artifacts; HEAVY enforces the full Fable depth. `root` (when
    given) lets must_read paths be checked for real existence. `pending` = files the
    edit under evaluation will touch (so multi-file escalation fires before it lands)."""
    grade = _effective_grade(spec, root, pending)
    # Weakening guard runs at SPEC validation too — PreToolUse authorizes edits on the SPEC
    # gate, so a softened spec must not pass it (not only blocked later at done).
    e: list[str] = list(_spec_weakened(spec, root))

    # ---- ALL grades: minimal viable spec ----
    rg, raw = spec.get("restated_goal", ""), spec.get("raw_goal", "")
    if not _nonempty(rg):
        e.append("restated_goal is empty — restate intent as 'achieve X without Y, scoped to Z'.")
    elif _norm(rg) == _norm(raw) and _nonempty(raw):
        e.append("restated_goal is identical to the raw ask — you under-interpreted; normalize it.")

    good_acc = [c for c in spec.get("acceptance_criteria", [])
                if isinstance(c, dict) and _nonempty((c.get("verify") or {}).get("value"))]
    if not good_acc:
        e.append("acceptance_criteria needs >=1 entry with a runnable command/check in verify.value (not prose).")
    for i, c in enumerate(spec.get("acceptance_criteria", [])):
        if isinstance(c, dict):
            vt = ((c.get("verify") or {}).get("type") or "").strip().lower()
            if vt and vt not in ACC_TYPES:
                e.append(f"acceptance_criteria[{i}].verify.type '{vt}' not in {sorted(ACC_TYPES)}.")

    if grade == "LIGHT":
        return e

    # ---- STANDARD and HEAVY ----
    if not [x for x in spec.get("non_goals", []) if _nonempty(x)]:
        e.append("non_goals is empty — fence the over-broad version you are NOT doing.")

    for i, a in enumerate(spec.get("ambiguities", [])):
        if not isinstance(a, dict):
            e.append(f"ambiguities[{i}] must be an object {{question,resolution,authority}}.")
        elif not (_nonempty(a.get("question")) and _nonempty(a.get("resolution")) and _nonempty(a.get("authority"))):
            e.append(f"ambiguities[{i}] needs question + resolution + the authority that resolved it.")

    mr = [m for m in spec.get("must_read", [])
          if isinstance(m, dict) and _nonempty(m.get("path")) and _nonempty(m.get("authority_reason"))]
    if not mr:
        e.append("must_read needs >=1 file justified by authority (a contract/boundary it owns).")
    if root is not None:
        for i, m in enumerate(spec.get("must_read", [])):
            if isinstance(m, dict) and _nonempty(m.get("path")) and not m.get("external"):
                if not (Path(root) / m["path"]).exists():
                    e.append(f"must_read[{i}] path '{m['path']}' not found under root — read a real file or set external:true.")

    good_alts = []
    for i, a in enumerate(spec.get("rejected_alternatives", [])):
        if not isinstance(a, dict):
            e.append(f"rejected_alternatives[{i}] must be an object.")
            continue
        # The Fable pattern is "name a category + the boundary it breaks" — the
        # taxonomy is descriptive, not prescriptive. Require a non-empty category
        # (recommend the canonical four) but don't reject a valid label we didn't
        # enumerate; the broken_boundary is what carries the reasoning.
        cat = (a.get("category") or "").strip()
        if not cat:
            e.append(f"rejected_alternatives[{i}] needs a category (recommended: {sorted(ALT_CATEGORIES)}).")
        if _nonempty(a.get("alternative")) and _nonempty(a.get("broken_boundary")) and cat:
            good_alts.append(a)
    if len(good_alts) < 2:
        e.append("need >=2 rejected_alternatives, each with a valid category + the broken boundary it violates.")

    for i, r in enumerate(spec.get("risks", [])):
        if not isinstance(r, dict):
            e.append(f"risks[{i}] must be an object.")
            continue
        sev = (r.get("severity") or "").strip().lower()
        if not sev:
            e.append(f"risks[{i}] needs a severity ({sorted(SEVERITIES)}) — rate by blast radius, not effort.")
        elif sev not in SEVERITIES:
            e.append(f"risks[{i}].severity '{sev}' not in {sorted(SEVERITIES)}.")
        if not _nonempty(r.get("mitigation")):
            e.append(f"risks[{i}] needs a runnable mitigation, not 'be careful'.")
        if sev in {"high", "blocking"} and not _nonempty(r.get("acceptance_ref")):
            e.append(f"risks[{i}] is {sev} — mirror it into an acceptance criterion (acceptance_ref).")
    # The contract promises STANDARD+ declares at least one risk; enforce it so the two
    # never drift (a spec with no risk block is "I see no blast radius" — make it explicit).
    good_risks = [r for r in spec.get("risks", []) if isinstance(r, dict)
                  and _nonempty(r.get("risk")) and not _is_placeholder_risk(r.get("risk"))
                  and (r.get("severity") or "").strip().lower() in SEVERITIES
                  and _nonempty(r.get("mitigation"))]
    if not good_risks:
        e.append("risks needs >=1 {risk, severity, mitigation} — name a real blast-radius risk, not 'none'.")

    # STANDARD anchor: the cheapest constraint — what must NOT change. Without it,
    # later risk/alternative/acceptance decisions have nothing to anchor on.
    if not [x for x in ((spec.get("constraints") or {}).get("invariant") or []) if _nonempty(_inv_text(x))]:
        e.append("constraints.invariant needs >=1 — what must NOT change "
                 "(don't delete prior work / don't leak / don't weaken a check).")

    if grade != "HEAVY":
        return e

    # ---- HEAVY only: full Fable depth (constraint provenance, mirror, validation) ----
    cons = spec.get("constraints") or {}
    arch = cons.get("architectural") or []
    if not arch:
        e.append("HEAVY: constraints.architectural needs >=1 {constraint, evidence_ref}.")
    for i, c in enumerate(arch):
        if not (isinstance(c, dict) and _nonempty(c.get("constraint")) and _nonempty(c.get("evidence_ref"))):
            e.append(f"HEAVY: constraints.architectural[{i}] must be {{constraint, evidence_ref}} — pin what proved it.")

    si = [s for s in spec.get("similar_implementations", [])
          if isinstance(s, dict) and _nonempty(s.get("path")) and _nonempty(s.get("why"))]
    if not si:
        e.append("HEAVY: similar_implementations needs >=1 {path, why} to mirror — avoid breaking an invariant.")

    return e


# ---------------------------------------------------------------- done gate ---
def gate_done(spec: dict, root=None, pending=None) -> list[str]:
    grade = _effective_grade(spec, root, pending)
    e = gate_spec(spec, root, pending)  # done implies spec still valid
    acc = [c for c in spec.get("acceptance_criteria", []) if isinstance(c, dict)]
    if not acc:
        e.append("no acceptance_criteria to verify.")
    for i, c in enumerate(acc):
        ev = c.get("evidence")
        if c.get("deferred") is True:
            # Strict `is True`: a truthy non-bool like "false" must NOT defer-and-skip.
            # Deferred is exempt from live evidence, but must NOT be a silent skip: it has
            # to record WHY it was dropped and what remains (the abandoned-task handoff).
            handoff = c.get("handoff") or c.get("reason") or (ev if isinstance(ev, str) else "")
            if not _nonempty(handoff):
                e.append(f"acceptance_criteria[{i}] is deferred with no handoff — record why it "
                         "was dropped and what remains (in evidence/handoff/reason).")
            continue
        if not _nonempty(ev):
            e.append(f"acceptance_criteria[{i}] has no evidence — run the check and cite live output (fail closed).")
        else:
            hit = next((m for m in FAKE_MARKERS if m in ev.lower()), None)
            if hit:
                e.append(f"acceptance_criteria[{i}] evidence reads as unfilled/fabricated ('{hit}') — "
                         "run it for real, or mark the criterion deferred with a handoff.")
    for ed, pat in _forbidden_hits(spec, root):
        e.append(f"edited '{ed}' which matches forbidden_paths '{pat}' — architecture/policy "
                 "conflict; revert that change or, if it is genuinely required, justify it by "
                 "moving the path out of forbidden_paths with a reason.")
    if grade == "HEAVY":
        good_obs = [o for o in spec.get("observations", [])
                    if isinstance(o, dict) and _nonempty(o.get("observation"))]
        if not good_obs:
            e.append("HEAVY: validation loop unrecorded — log >=1 observation (what a read revealed, "
                     "with changed_understanding + evidence_ref) so decisions trace to evidence.")
    return e


# ------------------------------------------------------------- contract text ---
def _contract_text(grade: str) -> str:
    """The full pass-conditions for this grade, delivered to the model UP FRONT so it
    writes a first-try-passing spec instead of discovering each rule by getting blocked.

    This is the data-grounded part: Fable's recorded sessions front-load the whole plan
    (restate -> bound -> reject alternatives -> declare acceptance) BEFORE touching code,
    rather than probing reactively. Agent runtimes default to the opposite (act, read the
    error, retry) — every such round re-reads the growing context (cache cost) and burns a
    turn. So we hand the model the exact contract once and tell it to emit the whole artifact
    in a single pass. The strict enum values are generated from the gate's own constants
    (ACC_TYPES / SEVERITIES); the per-field requirement lines are hand-maintained to mirror
    gate_spec/gate_done, and a unit test (tests Contract.*) asserts they stay in parity so a
    rule can't be enforced without being announced here."""
    # Only show the enums the grade actually uses — severity/category are STANDARD+
    # concepts, so listing them on a LIGHT task is pure noise (tokens).
    if grade == "LIGHT":
        enums = f"enums — verify.type in {sorted(ACC_TYPES)}."
    else:
        # Only verify.type and severity are STRICTLY enforced enums; category is lenient
        # (any non-empty label passes), so it is described in the field rule, not here.
        enums = (f"strict enums — verify.type in {sorted(ACC_TYPES)}; "
                 f"severity in {sorted(SEVERITIES)}.")
    head = [
        f"[fable-forge] GATE CONTRACT (grade {grade}). Edits are HARD-BLOCKED until "
        ".forge/spec.json passes the SPEC gate. Fill the spec COMPLETELY in ONE edit, then "
        "self-check once with `validate --gate spec`, then implement. Do NOT probe with a "
        "throwaway edit first — it is blocked and costs a wasted round. Required fields:",
        "- restated_goal: intent + constraint envelope; MUST differ from raw_goal (copying the ask = under-interpreted = blocked).",
        "- acceptance_criteria: >=1 {criterion, verify:{type,value}} where verify.value is a RUNNABLE command/check, not prose.",
    ]
    std = [
        "- non_goals: >=1 (the over-broad version you are NOT doing).",
        "- must_read: >=1 {path, authority_reason}; path MUST exist under root (or set external:true).",
        "- rejected_alternatives: >=2 {category, alternative, broken_boundary}; category must be non-empty "
        f"(recommended {sorted(ALT_CATEGORIES)}, but any descriptive label passes) and broken_boundary carries the reasoning.",
        "- risks: >=1 {risk, severity, mitigation}; the risk must be real (a placeholder like 'none'/'n/a'/'no risks' is rejected), mitigation runnable not 'be careful'. If severity high/blocking, also set acceptance_ref to a criterion.",
        "- constraints.invariant: >=1 (what must NOT change — don't delete prior work / leak / weaken a check).",
        "- ambiguities: optional, but any entry you add needs {question, resolution, authority} (who/what resolved it).",
    ]
    heavy = [
        "- constraints.architectural: >=1 {constraint, evidence_ref} (pin what proved each).",
        "- similar_implementations: >=1 {path, why} to mirror so you don't break an invariant.",
        "- observations (recorded as you go): >=1 with a non-empty `observation` "
        "(add changed_understanding + evidence_ref for traceability).",
    ]
    done = ("At DONE: every acceptance_criteria needs evidence = real live command output "
            "(words like 'tbd'/'assumed'/'would pass'/'n/a' are rejected). If you cannot run "
            "one, set deferred:true AND a handoff (why dropped + what remains) — a deferred "
            "criterion with no handoff is blocked. Never edit a forbidden_paths glob.")
    if grade == "LIGHT":
        body = head
    elif grade == "HEAVY":
        body = head + std + heavy
    else:
        body = head + std
    return "\n".join(body + [done, enums, "Do not narrate this contract to the user."])


# ----------------------------------------------------------------- commands ---
def cmd_contract(args) -> int:
    root = Path(args.root).resolve()
    spec, _ = load_spec(root)
    print(_contract_text(_effective_grade(spec or {}, root)))
    return 0


def cmd_scaffold(args) -> int:
    root = Path(args.root).resolve()
    fdir = root / FORGE_DIR
    fdir.mkdir(parents=True, exist_ok=True)
    fresh = not active_path(root).exists()  # no active task => this scaffold starts a new one
    grade = (args.grade or _grade_for(args.goal or "")).upper()
    if grade not in GRADE_RANK:
        grade = "STANDARD"
    gf = fdir / "GRADE"
    # Authoritative grade lock. On a FRESH task, overwrite any stale GRADE left by a closed
    # task (else a prior LIGHT would poison a later HEAVY). Mid-task, NEVER downgrade — and
    # if the lock is missing/invalid mid-task it was lost/tampered, so fail closed to HEAVY
    # rather than recreating a cheaper lock.
    if not fresh:
        prev = None
        if gf.exists():
            try:
                p = gf.read_text(encoding="utf-8").strip().upper()
                if p in GRADE_RANK:
                    prev = p
            except Exception:
                prev = None
        if prev is None:
            grade = "HEAVY"
        elif GRADE_RANK[prev] > GRADE_RANK[grade]:
            grade = prev
    gf.write_text(grade, encoding="utf-8")
    sp = spec_path(root)
    if fresh or not sp.exists():
        spec = dict(SPEC_TEMPLATE)
        spec["raw_goal"] = args.goal or ""
        spec["grade"] = grade
        sp.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
        if fresh:
            for stale in (fdir / "edits.txt", _spec_lock_path(root)):
                if stale.exists():
                    stale.unlink()  # a new task must not inherit prior edits / spec lock
    active_path(root).write_text(args.goal or "", encoding="utf-8")
    print(f"forge: task active at {fdir} (grade {grade})")
    return 0


LIGHT_RE = re.compile(r"\b(typo|comment|rename|reformat|lint|whitespace|indentation|"
                      r"docstring|wording|copy(?:edit)?)\b", re.I)  # dropped tweak/bump/bare-format
LIGHT_KO = ("오타", "주석", "포맷", "줄바꿈", "띄어쓰기", "문구", "오탈자")


def _grade_for(text: str) -> str:
    """Grade scales gate depth — the token lever. Default LIGHT (pay almost nothing:
    restated_goal + a runnable acceptance check, which is the part that actually caught
    bugs in benchmarking); HEAVY (auth/payments/security) pays full enforcement up front.
    A LIGHT task is escalated to STANDARD at RUNTIME by `_effective_grade` once the change
    proves non-trivial (spreads across >=2 files) — so simple fixes stay cheap and only
    real, spreading changes pay for the full decision spec."""
    if HEAVY_RE.search(text) or any(k in text for k in HEAVY_KO):
        return "HEAVY"
    if (STANDARD_RE.search(text) or NONTRIVIAL_VERB_RE.search(text)
            or any(k in text for k in STANDARD_KO)):
        return "STANDARD"
    if LIGHT_RE.search(text) or any(k in text for k in LIGHT_KO):
        return "LIGHT"  # only explicitly-small work (typo/comment/format/docstring/rename)
    return "STANDARD"  # unknown active work defaults to STANDARD, never cheap LIGHT


def cmd_validate(args) -> int:
    root = Path(args.root).resolve()
    spec, err = load_spec(root)
    if err:
        print(f"forge {args.gate} gate: BLOCKED\n  - {err}", file=sys.stderr)
        return 1
    # pending edit targets come via env (FORGE_PENDING json), never argv, so a path can't
    # inject gate flags.
    pending = None
    pj = os.environ.get("FORGE_PENDING")
    if pj:
        try:
            v = json.loads(pj)
            if isinstance(v, list):
                pending = [str(x) for x in v]
        except Exception:
            pending = None
    errs = gate_spec(spec, root, pending) if args.gate == "spec" else gate_done(spec, root, pending)
    if errs:
        print(f"forge {args.gate} gate: BLOCKED ({len(errs)} unmet)", file=sys.stderr)
        for x in errs:
            print(f"  - {x}", file=sys.stderr)
        return 1
    if args.gate == "spec":
        _write_spec_lock(spec, root)  # freeze the approved promises against later weakening
    print(f"forge {args.gate} gate: PASS")
    return 0


def cmd_active(args) -> int:
    return 0 if active_path(Path(args.root).resolve()).exists() else 1


def cmd_status(args) -> int:
    root = Path(args.root).resolve()
    if not active_path(root).exists():
        print("forge: no active task")
        return 0
    spec, err = load_spec(root)
    if err:
        print(f"forge: active task, spec error: {err}")
        return 0
    se = gate_spec(spec, root)
    print(f"forge: active | grade {spec.get('grade')} | phase {spec.get('phase')} | "
          f"spec gate {'PASS' if not se else f'BLOCKED ({len(se)})'}")
    return 0


def cmd_close(args) -> int:
    root = Path(args.root).resolve()
    spec, err = load_spec(root)
    if err:
        print(f"forge: cannot close — {err}", file=sys.stderr)
        return 1
    de = gate_done(spec, root)
    if de:
        forced = args.force and os.environ.get("FORGE_BYPASS") == "1"
        if not forced:
            print(f"forge: done gate BLOCKED ({len(de)}) — not closing:", file=sys.stderr)
            for x in de:
                print(f"  - {x}", file=sys.stderr)
            if args.force:
                print("  (refusing --force without FORGE_BYPASS=1 — forcing is an audited bypass)", file=sys.stderr)
            return 1
        print(f"forge: FORCED close past {len(de)} unmet done-gate item(s) via FORGE_BYPASS.", file=sys.stderr)
    # Clear per-task state so the NEXT task starts clean (no stale grade lock / edit log
    # leaking into it). Keep spec.json as the audit record of what was just closed.
    for f in (active_path(root), root / FORGE_DIR / "GRADE",
              root / FORGE_DIR / "edits.txt", _spec_lock_path(root)):
        if f.exists():
            f.unlink()
    print("forge: task closed")
    return 0


def cmd_toggle(args) -> int:
    root = Path(args.root).resolve()
    val = (args.set or "").lower()
    if val not in ("on", "off"):
        print("forge: --set must be on|off", file=sys.stderr)
        return 2
    scope = args.scope
    if scope == "machine":
        d = _machine_dir(); d.mkdir(parents=True, exist_ok=True)
        (d / "STATE").write_text(val, encoding="utf-8")
    elif scope == "session":
        if not args.sid:
            print("forge: session scope needs --sid (no session id available)", file=sys.stderr)
            return 2
        p = _session_state_path(root, args.sid); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(val, encoding="utf-8")
    else:  # project
        d = root / FORGE_DIR; d.mkdir(parents=True, exist_ok=True)
        (d / "STATE").write_text(val, encoding="utf-8")
        leg = d / "OFF"
        if leg.exists():
            leg.unlink()  # migrate the legacy binary marker into STATE
    print(f"forge: {scope} set {val} | effective now {effective_state(root, args.sid)}")
    return 0


def cmd_state(args) -> int:
    root = Path(args.root).resolve()
    eff = effective_state(root, args.sid)
    if args.verbose:
        sess, proj, mach = _scope_states(root, args.sid)
        print(f"effective {eff} | session {sess or '-'} | project {proj or '-'} | machine {mach or '-'}")
    else:
        print(eff)  # single token "on"/"off" — consumed by hooks + statusline
    return 0


def cmd_classify(args) -> int:
    t = args.text or ""
    if any(t.rstrip().endswith(s) for s in QUESTION_KO_ENDINGS):
        return 1  # question -> not work
    work = bool(WORK_RE.search(t)) or any(k in t for k in WORK_KO)
    return 0 if work else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="forge_gate")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scaffold"); sc.add_argument("--root", required=True)
    sc.add_argument("--goal", default=""); sc.add_argument("--grade", default="")
    sc.set_defaults(fn=cmd_scaffold)

    v = sub.add_parser("validate"); v.add_argument("--root", required=True)
    v.add_argument("--gate", choices=["spec", "done"], required=True)
    v.set_defaults(fn=cmd_validate)

    a = sub.add_parser("active"); a.add_argument("--root", required=True); a.set_defaults(fn=cmd_active)
    s = sub.add_parser("status"); s.add_argument("--root", required=True); s.set_defaults(fn=cmd_status)
    c = sub.add_parser("close"); c.add_argument("--root", required=True)
    c.add_argument("--force", action="store_true"); c.set_defaults(fn=cmd_close)
    cl = sub.add_parser("classify"); cl.add_argument("--text", default=""); cl.set_defaults(fn=cmd_classify)
    ct = sub.add_parser("contract"); ct.add_argument("--root", required=True); ct.set_defaults(fn=cmd_contract)
    tg = sub.add_parser("toggle"); tg.add_argument("--root", required=True)
    tg.add_argument("--scope", choices=SCOPES, default="project")
    tg.add_argument("--set", required=True); tg.add_argument("--sid", default="")
    tg.set_defaults(fn=cmd_toggle)
    sx = sub.add_parser("state"); sx.add_argument("--root", required=True)
    sx.add_argument("--sid", default=""); sx.add_argument("--verbose", action="store_true")
    sx.set_defaults(fn=cmd_state)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as exc:
        # Enforcement commands fail CLOSED (a gate bug must not silently disable
        # enforcement); housekeeping commands fail open. The host-side hook keeps
        # its own crash guard so a gate bug can't brick the tool pipeline.
        fail_closed = getattr(args, "cmd", "") in ("validate", "close")
        kind = "failing closed" if fail_closed else "failing open"
        print(f"forge_gate internal error ({kind}): {exc}", file=sys.stderr)
        return 1 if fail_closed else 0


if __name__ == "__main__":
    raise SystemExit(main())
