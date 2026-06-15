"""Regression tests for the wfb gate engine. Run: python3 -m unittest -q
(from ~/wfb) — stdlib only, no network, no fable-pack dependency."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gates"))
import wfb_gate as fg  # noqa: E402


def spec(**over):
    base = {
        "grade": "STANDARD",
        "raw_goal": "add a GET /health endpoint",
        "restated_goal": "Add a GET /health endpoint without changing existing routes, scoped to real.py.",
        "non_goals": ["no auth changes"],
        "constraints": {"invariant": ["existing routes must keep working"]},
        "must_read": [{"path": "real.py", "authority_reason": "owns the routing table"}],
        "rejected_alternatives": [
            {"category": "scope", "alternative": "new framework", "broken_boundary": "over-broad, no consumer"},
            {"category": "tempting_shortcut", "alternative": "skip tests", "broken_boundary": "hides regressions"},
        ],
        "risks": [{"risk": "route clash", "severity": "medium", "mitigation": "grep routes first"}],
        "acceptance_criteria": [{"criterion": "200", "verify": {"type": "command", "value": "curl -sf localhost/health"}}],
    }
    base.update(over)
    return base


class GateSpec(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "real.py").write_text("x=1")

    def test_standard_valid_passes(self):
        self.assertEqual(fg.gate_spec(spec(), self.d), [])

    def test_light_minimal_passes(self):
        s = {"grade": "LIGHT", "raw_goal": "fix typo",
             "restated_goal": "Correct 'recieve' spelling without touching surrounding copy.",
             "acceptance_criteria": [{"criterion": "fixed", "verify": {"type": "grep", "value": "! grep -q recieve f"}}]}
        self.assertEqual(fg.gate_spec(s, self.d), [])

    def test_restated_equal_raw_blocks(self):
        e = fg.gate_spec(spec(restated_goal=spec()["raw_goal"]), self.d)
        self.assertTrue(any("identical to the raw ask" in x for x in e))

    def test_missing_invariant_blocks(self):
        e = fg.gate_spec(spec(constraints={"invariant": []}), self.d)
        self.assertTrue(any("constraints.invariant" in x for x in e))

    def test_nonexistent_must_read_blocks(self):
        e = fg.gate_spec(spec(must_read=[{"path": "ghost.py", "authority_reason": "x"}]), self.d)
        self.assertTrue(any("not found under root" in x for x in e))

    def test_external_must_read_allowed(self):
        s = spec(must_read=[{"path": "/etc/hosts", "authority_reason": "x", "external": True}])
        self.assertEqual(fg.gate_spec(s, self.d), [])

    def test_one_rejected_alt_blocks_standard(self):
        e = fg.gate_spec(spec(rejected_alternatives=[
            {"category": "scope", "alternative": "a", "broken_boundary": "b"}]), self.d)
        self.assertTrue(any("rejected_alternatives" in x for x in e))

    def test_noncanonical_category_accepted(self):
        # the taxonomy is descriptive; a sensible label we didn't enumerate must pass
        s = spec(rejected_alternatives=[
            {"category": "dependency", "alternative": "add lib X", "broken_boundary": "new dep, no consumer"},
            {"category": "performance", "alternative": "cache all", "broken_boundary": "premature, no measured need"}])
        self.assertEqual(fg.gate_spec(s, self.d), [])

    def test_empty_category_blocks(self):
        e = fg.gate_spec(spec(rejected_alternatives=[
            {"category": "", "alternative": "a", "broken_boundary": "b"},
            {"category": "scope", "alternative": "c", "broken_boundary": "d"}]), self.d)
        self.assertTrue(any("needs a category" in x for x in e))

    def test_risk_without_severity_blocks(self):
        e = fg.gate_spec(spec(risks=[{"risk": "x", "mitigation": "y"}]), self.d)
        self.assertTrue(any("needs a severity" in x for x in e))

    def test_high_risk_needs_mirror(self):
        e = fg.gate_spec(spec(risks=[{"risk": "x", "severity": "high", "mitigation": "y"}]), self.d)
        self.assertTrue(any("acceptance_ref" in x for x in e))

    def test_heavy_requires_arch_evidence_and_similar(self):
        e = fg.gate_spec(spec(grade="HEAVY"), self.d)
        self.assertTrue(any("architectural" in x for x in e))
        self.assertTrue(any("similar_implementations" in x for x in e))

    def test_bad_acceptance_type_blocks(self):
        s = spec()
        s["acceptance_criteria"][0]["verify"]["type"] = "vibes"
        self.assertTrue(any("verify.type" in x for x in fg.gate_spec(s, self.d)))

    def test_no_risks_blocks_standard(self):
        # The contract promises STANDARD+ declares >=1 risk; the gate must enforce it
        # (otherwise contract<->gate drift). An empty risks list is blocked.
        e = fg.gate_spec(spec(risks=[]), self.d)
        self.assertTrue(any("risks needs >=1" in x for x in e))

    def test_placeholder_risk_variants_block(self):
        # Placeholders must not satisfy the >=1-risk rule even with punctuation/casing.
        for txt in ("none", "None.", "N/A", "n/a.", "No risks!", "nothing", "  no  "):
            s = spec(risks=[{"risk": txt, "severity": "low", "mitigation": "echo ok"}])
            self.assertTrue(any("blast-radius" in x for x in fg.gate_spec(s, self.d)),
                            f"placeholder risk {txt!r} should block")
        # A real risk that merely starts with 'no' must NOT be falsely rejected.
        s = spec(risks=[{"risk": "no fallback path if cache misses", "severity": "low", "mitigation": "add default"}])
        self.assertEqual(fg.gate_spec(s, self.d), [])


class GateDone(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "real.py").write_text("x=1")

    def test_no_evidence_blocks(self):
        self.assertTrue(any("no evidence" in x for x in fg.gate_done(spec(), self.d)))

    def test_fake_evidence_blocks(self):
        s = spec()
        s["acceptance_criteria"][0]["evidence"] = "assumed it would pass"
        self.assertTrue(any("fabricated" in x for x in fg.gate_done(s, self.d)))

    def test_real_evidence_passes(self):
        s = spec()
        s["acceptance_criteria"][0]["evidence"] = "curl -> HTTP 200 OK"
        self.assertEqual(fg.gate_done(s, self.d), [])

    def test_deferred_criterion_skips_fake_check(self):
        s = spec()
        s["acceptance_criteria"][0]["evidence"] = "pending human deploy"  # serves as handoff
        s["acceptance_criteria"][0]["deferred"] = True
        self.assertEqual(fg.gate_done(s, self.d), [])

    def test_deferred_without_handoff_blocks(self):
        # A deferred criterion must record WHY it was dropped + what remains — a silent
        # deferred (no evidence/handoff/reason) is the abandoned-task bypass; block it.
        s = spec()
        s["acceptance_criteria"][0]["deferred"] = True
        s["acceptance_criteria"][0].pop("evidence", None)
        self.assertTrue(any("deferred with no handoff" in x for x in fg.gate_done(s, self.d)))

    def test_forbidden_path_edit_blocks_done(self):
        (self.d / ".wfb").mkdir(exist_ok=True)
        (self.d / ".wfb" / "edits.txt").write_text("config/policy.py\nsrc/main.py\n")
        s = spec(forbidden_paths=["config/*"])
        s["acceptance_criteria"][0]["evidence"] = "ran OK"
        self.assertTrue(any("forbidden_paths" in x for x in fg.gate_done(s, self.d)))

    def test_no_forbidden_edit_passes(self):
        (self.d / ".wfb").mkdir(exist_ok=True)
        (self.d / ".wfb" / "edits.txt").write_text("src/main.py\n")
        s = spec(forbidden_paths=["config/*"])
        s["acceptance_criteria"][0]["evidence"] = "ran OK"
        self.assertEqual(fg.gate_done(s, self.d), [])

    def test_heavy_requires_observation(self):
        s = spec(grade="HEAVY")
        s["constraints"] = {"invariant": ["x"], "architectural": [{"constraint": "c", "evidence_ref": "real.py"}]}
        s["similar_implementations"] = [{"path": "real.py", "why": "mirror"}]
        s["acceptance_criteria"][0]["evidence"] = "ran OK"
        self.assertTrue(any("validation loop" in x for x in fg.gate_done(s, self.d)))
        s["observations"] = [{"observation": "real.py defines routes via a dict", "changed_understanding": True}]
        self.assertEqual(fg.gate_done(s, self.d), [])


class Adversarial(unittest.TestCase):
    """Try to break or game the gate; verify it holds (and document inherent limits)."""
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "real.py").write_text("x=1")

    def _scaffold(self, goal):
        fg.cmd_scaffold(type("A", (), {"root": str(self.d), "goal": goal, "grade": ""})())

    def _load(self):
        return json.loads((self.d / ".wfb" / "spec.json").read_text())

    def test_grade_lock_blocks_silent_downgrade(self):
        # HEAVY task auto-graded + locked in .wfb/GRADE
        self._scaffold("secure auth token migration for payments")
        self.assertEqual((self.d / ".wfb" / "GRADE").read_text().strip(), "HEAVY")
        # attacker rewrites spec.json claiming LIGHT + minimal fields
        s = self._load()
        s["grade"] = "LIGHT"
        s["restated_goal"] = "Migrate auth tokens without dropping sessions, scoped to auth.py."
        s["acceptance_criteria"] = [{"criterion": "ok", "verify": {"type": "command", "value": "pytest"}}]
        e = fg.gate_spec(s, self.d)
        # HEAVY is still enforced (GRADE file wins): many unmet items, not a LIGHT pass
        self.assertGreaterEqual(len(e), 4, e)

    def test_nondict_spec_blocked(self):
        (self.d / ".wfb").mkdir(exist_ok=True)
        (self.d / ".wfb" / "spec.json").write_text("[1,2,3]")
        rc = fg.cmd_validate(type("A", (), {"root": str(self.d), "gate": "spec"})())
        self.assertEqual(rc, 1)

    def test_garbage_json_blocked(self):
        (self.d / ".wfb").mkdir(exist_ok=True)
        (self.d / ".wfb" / "spec.json").write_text("{ not json at all ")
        rc = fg.cmd_validate(type("A", (), {"root": str(self.d), "gate": "spec"})())
        self.assertEqual(rc, 1)

    def test_internal_error_fails_closed(self):
        # main() wraps gate calls; a non-dict spec slipping past would fail CLOSED (rc 1)
        rc = fg.main(["validate", "--root", str(self.d), "--gate", "spec"])
        self.assertEqual(rc, 1)  # no spec file -> blocked

    def test_KNOWN_LIMIT_trivial_command_passes(self):
        # DOCUMENTED inherent limit: the gate checks FORM, not SEMANTICS. A trivially
        # passing command ('true') is "runnable", so it passes. Catching this needs the
        # optional judge layer, not the deterministic gate. Asserted so the limit is explicit.
        s = spec()
        s["acceptance_criteria"] = [{"criterion": "ok", "verify": {"type": "command", "value": "true"}}]
        self.assertEqual(fg.gate_spec(s, self.d), [])

    def test_KNOWN_LIMIT_shallow_but_wellformed_passes(self):
        # low-effort-but-structurally-valid rejected_alternatives pass (form, not depth)
        s = spec(rejected_alternatives=[
            {"category": "scope", "alternative": "x", "broken_boundary": "y"},
            {"category": "scope", "alternative": "a", "broken_boundary": "b"}])
        self.assertEqual(fg.gate_spec(s, self.d), [])


class FableMethod(unittest.TestCase):
    """Verify the gate enforces each axis of the Fable decision pattern: removing the
    element for that axis must make the gate block."""
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "real.py").write_text("x=1")

    def _blocks_when(self, **drop):
        s = spec(**drop)
        return fg.gate_spec(s, self.d)

    def test_axis_goal_interpretation(self):           # restated_goal == raw -> block
        self.assertTrue(self._blocks_when(restated_goal=spec()["raw_goal"]))

    def test_axis_scope_by_negation(self):             # non_goals empty -> block
        self.assertTrue(self._blocks_when(non_goals=[]))

    def test_axis_context_by_authority(self):          # must_read missing -> block
        self.assertTrue(self._blocks_when(must_read=[]))

    def test_axis_alternative_analysis(self):          # <2 rejected -> block
        self.assertTrue(self._blocks_when(rejected_alternatives=[]))

    def test_axis_constraint_extraction(self):         # no invariant -> block
        self.assertTrue(self._blocks_when(constraints={"invariant": []}))

    def test_axis_risk_reasoning(self):                # risk without severity -> block
        self.assertTrue(self._blocks_when(risks=[{"risk": "x", "mitigation": "y"}]))

    def test_axis_acceptance_design(self):             # no runnable acceptance -> block
        self.assertTrue(self._blocks_when(acceptance_criteria=[{"criterion": "x"}]))


class Classify(unittest.TestCase):
    def test_work_vs_question(self):
        self.assertEqual(fg.cmd_classify(type("A", (), {"text": "fix the auth bug"})), 0)
        self.assertEqual(fg.cmd_classify(type("A", (), {"text": "이거 어떻게 동작하나요?"})), 1)

    def test_grade_for(self):
        # HEAVY: blast-radius / security / data / migration
        self.assertEqual(fg._grade_for("fix payment auth token"), "HEAVY")
        self.assertEqual(fg._grade_for("migrate the user table schema"), "HEAVY")
        # LIGHT: only explicitly-trivial work
        self.assertEqual(fg._grade_for("fix a typo in the comment"), "LIGHT")
        self.assertEqual(fg._grade_for("rename the variable"), "LIGHT")
        # STANDARD: real engineering difficulty, and unknown active work (NOT cheap LIGHT)
        self.assertEqual(fg._grade_for("fix the race condition in the scheduler"), "STANDARD")
        self.assertEqual(fg._grade_for("implement an LRU cache"), "STANDARD")
        self.assertEqual(fg._grade_for("add a sort function"), "STANDARD")

    def test_grade_for_precision(self):
        # explicit-trivial wins over ambiguous noun-verbs
        self.assertEqual(fg._grade_for("fix a typo in the build script"), "LIGHT")
        self.assertEqual(fg._grade_for("fix wording on the Create button"), "LIGHT")
        # bare delete / token are no longer wrongly HEAVY
        self.assertEqual(fg._grade_for("delete unused import"), "STANDARD")
        self.assertEqual(fg._grade_for("optimize token budget"), "STANDARD")
        # auth synonyms ARE heavy
        for t in ("rename the OAuth provider", "add JWT validation", "add authentication"):
            self.assertEqual(fg._grade_for(t), "HEAVY", t)

    def test_heavy_path_segment_precision(self):
        def grade(rel):
            d = Path(tempfile.mkdtemp()); (d / ".wfb").mkdir(); (d / ".wfb" / "GRADE").write_text("LIGHT")
            (d / ".wfb" / "edits.txt").write_text(f"{d}/{rel}\n", encoding="utf-8")
            return fg._effective_grade({}, d)
        # compound dir names / lookalike files are NOT heavy
        self.assertEqual(grade("payment-app/utils.py"), "LIGHT")
        self.assertEqual(grade("immigration_notes.md"), "LIGHT")
        # real auth/migration/sql files ARE heavy
        for rel in ("db/migrations/0003.py", "app/auth/login.py", "src/oauth/p.py", "q.sql"):
            self.assertEqual(grade(rel), "HEAVY", rel)

    def test_effective_grade_escalates_on_multifile(self):
        d = Path(tempfile.mkdtemp())
        (d / ".wfb").mkdir()
        (d / ".wfb" / "GRADE").write_text("LIGHT", encoding="utf-8")
        self.assertEqual(fg._effective_grade({}, d), "LIGHT")  # no edits yet
        (d / ".wfb" / "edits.txt").write_text("a.py\n", encoding="utf-8")
        self.assertEqual(fg._effective_grade({}, d), "LIGHT")  # one file stays LIGHT
        (d / ".wfb" / "edits.txt").write_text("a.py\nb.py\n", encoding="utf-8")
        self.assertEqual(fg._effective_grade({}, d), "STANDARD")  # >=2 files escalates

    def test_effective_grade_never_downgrades_heavy(self):
        d = Path(tempfile.mkdtemp())
        (d / ".wfb").mkdir()
        (d / ".wfb" / "GRADE").write_text("HEAVY", encoding="utf-8")
        (d / ".wfb" / "edits.txt").write_text("a.py\nb.py\n", encoding="utf-8")
        self.assertEqual(fg._effective_grade({}, d), "HEAVY")  # escalation is up-only


class Contract(unittest.TestCase):
    """The up-front contract must announce EVERY pass-condition the gate enforces, so a
    model writes a first-try-passing spec instead of discovering each rule by getting
    blocked. If a gate rule exists with no contract line, the reactive bounce returns."""

    def test_light_minimal_only(self):
        t = fg._contract_text("LIGHT")
        self.assertIn("restated_goal", t)
        self.assertIn("acceptance_criteria", t)
        # LIGHT must NOT demand the STANDARD decision artifacts (token lever).
        self.assertNotIn("rejected_alternatives", t)
        self.assertNotIn("constraints.invariant", t)

    def test_standard_lists_all_blocking_fields(self):
        t = fg._contract_text("STANDARD")
        for needle in ("restated_goal", "differ from raw_goal", "non_goals",
                       "must_read", "authority_reason", "MUST exist",
                       "rejected_alternatives", "risks", "placeholder like 'none'",
                       "constraints.invariant", "acceptance_ref", "ambiguities",
                       "deferred", "forbidden_paths"):
            self.assertIn(needle, t, needle)

    def test_heavy_adds_depth(self):
        t = fg._contract_text("HEAVY")
        self.assertIn("constraints.architectural", t)
        self.assertIn("similar_implementations", t)
        self.assertIn("observations", t)

    def test_enums_match_gate_constants(self):
        # The contract's enum values are generated FROM the gate constants — assert they
        # stay in sync so a model is never told a value the gate will reject.
        t = fg._contract_text("STANDARD")
        for v in fg.ACC_TYPES:
            self.assertIn(v, t)
        for v in fg.SEVERITIES:
            self.assertIn(v, t)
        for v in fg.ALT_CATEGORIES:
            self.assertIn(v, t)

    def test_contract_command_reads_grade_lock(self):
        with tempfile.TemporaryDirectory() as d:
            fg.main(["scaffold", "--root", d, "--goal", "add auth token check"])  # HEAVY
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                fg.main(["contract", "--root", d])
            self.assertIn("similar_implementations", buf.getvalue())


class DynamicGrade(unittest.TestCase):
    """Default LIGHT + runtime escalation, hardened per review."""

    def test_fresh_scaffold_overwrites_stale_grade(self):
        d = Path(tempfile.mkdtemp())
        fg.main(["scaffold", "--root", str(d), "--goal", "fix a typo"])
        self.assertEqual((d / ".wfb" / "GRADE").read_text().strip(), "LIGHT")
        (d / ".wfb" / "ACTIVE").unlink()  # simulate a closed task leaving GRADE behind
        fg.main(["scaffold", "--root", str(d), "--goal", "add auth token check"])
        self.assertEqual((d / ".wfb" / "GRADE").read_text().strip(), "HEAVY")  # not stale LIGHT

    def test_close_clears_task_state(self):
        d = Path(tempfile.mkdtemp())
        fg.main(["scaffold", "--root", str(d), "--goal", "fix typo"])
        (d / ".wfb" / "edits.txt").write_text("a.py\n", encoding="utf-8")
        s = json.load(open(d / ".wfb" / "spec.json"))
        s["restated_goal"] = "fix the typo, scoped"; s["acceptance_criteria"] = [
            {"criterion": "c", "verify": {"type": "command", "value": "true"}, "evidence": "ran ok"}]
        json.dump(s, open(d / ".wfb" / "spec.json", "w"))
        fg.main(["close", "--root", str(d)])
        self.assertFalse((d / ".wfb" / "GRADE").exists())
        self.assertFalse((d / ".wfb" / "edits.txt").exists())
        self.assertFalse((d / ".wfb" / "ACTIVE").exists())

    def test_heavy_path_escalates_to_heavy(self):
        d = Path(tempfile.mkdtemp()); (d / ".wfb").mkdir()
        (d / ".wfb" / "GRADE").write_text("LIGHT")
        (d / ".wfb" / "edits.txt").write_text("db/migrations/0003_add.py\n", encoding="utf-8")
        self.assertEqual(fg._effective_grade({}, d), "HEAVY")  # touching a migration => HEAVY
        # a pending edit to an auth file also escalates before it lands
        d2 = Path(tempfile.mkdtemp()); (d2 / ".wfb").mkdir(); (d2 / ".wfb" / "GRADE").write_text("LIGHT")
        self.assertEqual(fg._effective_grade({}, d2, pending=[str(d2 / "app/auth/login.py")]), "HEAVY")

    def test_pending_escalates_before_edit_lands(self):
        d = Path(tempfile.mkdtemp())
        (d / ".wfb").mkdir(); (d / ".wfb" / "GRADE").write_text("LIGHT")
        (d / ".wfb" / "edits.txt").write_text("/x/a.py\n", encoding="utf-8")  # 1 file so far
        self.assertEqual(fg._effective_grade({}, d), "LIGHT")
        self.assertEqual(fg._effective_grade({}, d, pending=[str(d / "b.py")]), "STANDARD")

    def test_canonical_path_dedup(self):
        d = Path(tempfile.mkdtemp()); (d / ".wfb").mkdir()
        (d / ".wfb" / "edits.txt").write_text(f"a.py\n./a.py\n{d}/a.py\n", encoding="utf-8")
        self.assertEqual(fg._edited_file_count(d), 1)  # same file, three spellings

    def test_absolute_wfb_path_excluded(self):
        d = Path(tempfile.mkdtemp()); (d / ".wfb").mkdir()
        (d / ".wfb" / "edits.txt").write_text(f"{d}/.wfb/spec.json\nreal.py\n", encoding="utf-8")
        self.assertEqual(fg._edited_file_count(d), 1)  # only real.py, .wfb excluded

    def test_active_without_grade_fails_closed_heavy(self):
        d = Path(tempfile.mkdtemp()); (d / ".wfb").mkdir()
        (d / ".wfb" / "ACTIVE").write_text("x")  # active task but GRADE lock missing/tampered
        self.assertEqual(fg._effective_grade({}, d), "HEAVY")  # strictest floor, never a downgrade

    def test_midtask_lost_grade_rescaffold_forces_heavy(self):
        d = Path(tempfile.mkdtemp())
        fg.main(["scaffold", "--root", str(d), "--goal", "fix bug"])  # LIGHT, ACTIVE set
        (d / ".wfb" / "GRADE").unlink()  # lock lost mid-task
        fg.main(["scaffold", "--root", str(d), "--goal", "fix bug"])  # re-scaffold (still ACTIVE)
        self.assertEqual((d / ".wfb" / "GRADE").read_text().strip(), "HEAVY")

    def test_spec_cannot_weaken_forbidden_after_approval(self):
        d = Path(tempfile.mkdtemp()); (d / ".wfb").mkdir()
        approved = {"forbidden_paths": ["config/*"],
                    "acceptance_criteria": [{"criterion": "c", "verify": {"type": "command", "value": "true"}}]}
        fg._write_spec_lock(approved, d)  # snapshot at spec-gate pass
        weakened = dict(approved); weakened["forbidden_paths"] = []  # removed the guard
        self.assertTrue(any("weakened" in x for x in fg._spec_weakened(weakened, d)))
        # strengthening (adding another forbidden path) is fine
        stronger = dict(approved); stronger["forbidden_paths"] = ["config/*", "secrets/*"]
        self.assertEqual(fg._spec_weakened(stronger, d), [])


class OnOffState(unittest.TestCase):
    """3-scope on/off: session > project > machine > default ON."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.home = tempfile.mkdtemp()
        self._old = os.environ.get("WFB_HOME")
        os.environ["WFB_HOME"] = self.home  # isolate machine scope from the real ~/.wfb

    def tearDown(self):
        if self._old is None:
            os.environ.pop("WFB_HOME", None)
        else:
            os.environ["WFB_HOME"] = self._old

    def tog(self, scope, val, sid=""):
        fg.main(["toggle", "--root", str(self.d), "--scope", scope, "--set", val] + (["--sid", sid] if sid else []))

    def test_default_on(self):
        self.assertEqual(fg.effective_state(self.d, "S1"), "on")

    def test_machine_off_then_project_on_overrides(self):
        self.tog("machine", "off")
        self.assertEqual(fg.effective_state(self.d, "S1"), "off")
        self.tog("project", "on")
        self.assertEqual(fg.effective_state(self.d, "S1"), "on")

    def test_session_overrides_project(self):
        self.tog("project", "off")
        self.tog("session", "on", "HARD")
        self.assertEqual(fg.effective_state(self.d, "HARD"), "on")   # the one hard session
        self.assertEqual(fg.effective_state(self.d, "OTHER"), "off")  # everyone else inherits

    def test_legacy_off_marker_still_off(self):
        (self.d / ".wfb").mkdir(parents=True, exist_ok=True)
        (self.d / ".wfb" / "OFF").write_text("", encoding="utf-8")
        self.assertEqual(fg.effective_state(self.d, "S1"), "off")

    def test_machine_dir_distinct_from_home_project(self):
        old = os.environ.pop("WFB_HOME", None)
        try:
            md = fg._machine_dir().resolve()
            self.assertNotEqual(md, (Path.home() / ".wfb").resolve(),
                                "machine state must not collide with a $HOME project's .wfb")
        finally:
            if old is not None:
                os.environ["WFB_HOME"] = old

    def test_session_sid_cannot_escape_sessions_dir(self):
        evil = "../../../../tmp/wfb_pwn"
        self.tog("session", "off", evil)
        p = fg._session_state_path(self.d, evil).resolve()
        sessions = (self.d / ".wfb" / "sessions").resolve()
        self.assertTrue(str(p).startswith(str(sessions)), f"{p} escaped {sessions}")
        self.assertEqual(fg.effective_state(self.d, evil), "off")

    def test_toggle_project_migrates_legacy_marker(self):
        (self.d / ".wfb").mkdir(parents=True, exist_ok=True)
        (self.d / ".wfb" / "OFF").write_text("", encoding="utf-8")
        self.tog("project", "on")  # should clear the legacy OFF and set STATE=on
        self.assertFalse((self.d / ".wfb" / "OFF").exists())
        self.assertEqual(fg.effective_state(self.d, "S1"), "on")


class HookGuards(unittest.TestCase):
    """Hook-level enforcement: rename dest parsing + gate-state edit protection."""

    def setUp(self):
        hooks = str(Path(__file__).resolve().parents[1] / "adapters" / "hooks")
        if hooks not in sys.path:
            sys.path.insert(0, hooks)

    def test_move_to_dest_parsed(self):
        import common
        got = set(common.edited_paths({"tool_name": "apply_patch", "tool_input": {
            "command": "*** Update File: a.py\n*** Move to: b.py"}}))
        self.assertEqual(got, {"a.py", "b.py"})  # rename dest counted

    def test_gate_state_protected_spec_allowed(self):
        import pre_tool_use as pt
        import common
        root = str(Path(tempfile.mkdtemp()))  # real dir so realpath is stable
        self.assertTrue(pt._is_protected_state(f"{root}/.wfb/GRADE", root))
        self.assertTrue(pt._is_protected_state(".wfb/edits.txt", root))
        self.assertTrue(pt._is_protected_state(f"{root}/.wfb/STATE", root))
        self.assertFalse(pt._is_protected_state(f"{root}/.wfb/spec.json", root))
        self.assertTrue(common.is_spec_authoring(f"{root}/.wfb/spec.json", root))
        self.assertFalse(pt._is_protected_state("src/main.py", root))
        # canonicalization: '.wfb/../src/a.py' is NOT gate state (escapes the substring trap)
        self.assertFalse(pt._is_protected_state(".wfb/../src/a.py", root))
        self.assertFalse(common.under_wfb(".wfb/../src/a.py", root))


if __name__ == "__main__":
    unittest.main()
