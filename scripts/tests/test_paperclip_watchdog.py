"""Tests for scripts/paperclip-watchdog.py.

Run with:

    uv run --quiet --with pytest python -m pytest scripts/tests -q

Every test feeds synthetic runs and issues to the pure decision function, so
nothing here calls a live Paperclip server, touches launchd, or writes outside
a temporary directory. Every agent and company name here is invented for the
test.
"""

import json
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("paperclip_watchdog", SCRIPTS / "paperclip-watchdog.py")
wd = importlib.util.module_from_spec(_spec)
sys.modules["paperclip_watchdog"] = wd
_spec.loader.exec_module(wd)

NOW = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
LABEL = "label-scope-creep"

CFG = {
    "companyId": "c1",
    "agents": [
        {"key": "scoper", "id": "a-scoper", "name": "Scoper", "runsPerDay": 2},
        {"key": "research", "id": None, "name": "Research lead", "runsPerDay": 1},
    ],
    "watchdog": {"authFailureBurst": 3, "authFailurePattern": "OAuth session expired",
                 "scopeAgent": "scoper", "leads": {"research": "research"}},
}

AGENTS = [
    {"id": "a-scoper", "name": "Scoper", "status": "idle"},
    {"id": "a-research", "name": "Research lead", "status": "idle"},
]


def run(agent, at, status="succeeded", error=None, error_code=None, run_id=None, finished_at=None):
    return {"id": run_id, "agentId": agent, "createdAt": at, "finishedAt": finished_at or at,
            "status": status, "error": error, "errorCode": error_code}


def issue(id_, **over):
    base = {
        "id": id_, "identifier": id_.upper(), "status": "todo", "createdByUserId": None,
        "createdByAgentId": "a-scoper", "originKind": "manual", "assigneeAgentId": None,
        "assigneeUserId": None, "labelIds": [],
    }
    base.update(over)
    return base


def decide(runs=(), issues=(), agents=AGENTS, seen=()):
    return wd.decide(CFG, list(runs), list(issues), list(agents), set(seen), LABEL, NOW)


class RunCapTests(unittest.TestCase):
    def test_agent_at_cap_today_is_paused(self):
        d = decide(runs=[run("a-scoper", "2026-09-26T01:00:00Z"), run("a-scoper", "2026-09-26T09:00:00Z")])
        self.assertEqual([(a.method, a.path) for a in d.actions], [("POST", "/api/agents/a-scoper/pause")])

    def test_runs_from_yesterday_do_not_count(self):
        d = decide(runs=[run("a-scoper", "2026-09-25T23:59:00Z"), run("a-scoper", "2026-09-26T09:00:00Z")])
        self.assertEqual(d.actions, [])

    def test_agent_without_config_id_is_matched_by_name(self):
        d = decide(runs=[run("a-research", "2026-09-26T09:00:00Z")])
        self.assertEqual([a.path for a in d.actions], ["/api/agents/a-research/pause"])

    def test_paused_agent_is_not_paused_again(self):
        agents = [dict(AGENTS[0], status="paused"), AGENTS[1]]
        d = decide(runs=[run("a-scoper", "2026-09-26T01:00:00Z")] * 3, agents=agents)
        self.assertEqual(d.actions, [])

    def test_a_cap_paused_agent_is_never_resumed_by_the_watchdog(self):
        """A cap pause has no new-day resume. Nothing in this script ever sends
        a resume for a capped agent, so a person is the only way back. Every
        `resume` this script sends belongs to a twin swap, never to a cap."""
        agents = [dict(AGENTS[0], status="paused"), AGENTS[1]]
        runs = [run("a-scoper", "2026-09-26T01:00:00Z")] * 5
        for at in ("2026-09-26T15:00:00Z", "2026-09-27T09:00:00Z", "2026-10-01T09:00:00Z"):
            later = wd.parse_ts(at)
            d = wd.decide(CFG, runs, [], agents, set(), LABEL, later)
            self.assertFalse(any("/resume" in a.path for a in d.actions), at)


BREAKER_CFG = {
    "companyId": "c1",
    "agents": [
        {"key": "scoper", "id": "a-scoper", "name": "Scoper"},
        {"key": "research", "id": "a-research", "name": "Research lead"},
    ],
    "watchdog": {"authFailureBurst": 3, "authFailurePattern": "OAuth session expired"},
    "runCaps": {
        "claude_local": {"agents": {"scoper": 2}, "harnessTotal": 3},
        "default": {"harnessTotal": 1},
    },
}

BREAKER_AGENTS = [
    {"id": "a-scoper", "name": "Scoper", "status": "idle", "adapterType": "claude_local"},
    {"id": "a-research", "name": "Research lead", "status": "idle", "adapterType": "claude_local"},
]


class RunCapBreakerTests(unittest.TestCase):
    def decide(self, runs=(), agents=BREAKER_AGENTS, cfg=BREAKER_CFG):
        return wd.decide(cfg, list(runs), [], list(agents), set(), LABEL, NOW)

    def test_agent_at_its_own_adapter_cap_is_paused(self):
        d = self.decide(runs=[run("a-scoper", "2026-09-26T01:00:00Z"), run("a-scoper", "2026-09-26T09:00:00Z")])
        self.assertIn(("POST", "/api/agents/a-scoper/pause"), [(a.method, a.path) for a in d.actions])

    def test_adapter_total_cap_pauses_every_agent_on_it(self):
        runs = [run("a-scoper", "2026-09-26T01:00:00Z"), run("a-research", "2026-09-26T02:00:00Z"),
                run("a-research", "2026-09-26T03:00:00Z")]
        d = self.decide(runs=runs)
        paths = {a.path for a in d.actions}
        self.assertIn("/api/agents/a-scoper/pause", paths)
        self.assertIn("/api/agents/a-research/pause", paths)

    def test_unknown_adapter_falls_back_to_default(self):
        agents = [dict(BREAKER_AGENTS[0], adapterType="other_local")]
        d = self.decide(runs=[run("a-scoper", "2026-09-26T01:00:00Z")], agents=agents)
        self.assertEqual([a.path for a in d.actions], ["/api/agents/a-scoper/pause"])

    def test_no_run_caps_configured_changes_nothing(self):
        cfg = {**BREAKER_CFG, "runCaps": None}
        d = self.decide(runs=[run("a-scoper", "2026-09-26T01:00:00Z")] * 5, cfg=cfg)
        self.assertEqual(d.actions, [])

    def test_under_every_cap_plans_nothing(self):
        d = self.decide(runs=[run("a-scoper", "2026-09-26T01:00:00Z")])
        self.assertEqual(d.actions, [])

    def test_unmatched_configured_agent_warns_instead_of_silently_dropping(self):
        cfg = {**BREAKER_CFG,
               "agents": BREAKER_CFG["agents"] + [{"key": "engineering", "id": "a-eng", "name": "Engineering lead"}]}
        d = self.decide(cfg=cfg)
        self.assertTrue(any("Engineering lead" in w for w in d.warnings))

    def test_adapter_with_no_entry_and_no_default_raises(self):
        cfg = {**BREAKER_CFG, "runCaps": {"other_local": {"harnessTotal": 1}}}
        with self.assertRaises(wd.PaperclipError):
            self.decide(cfg=cfg)

    def test_adapter_falling_back_to_default_warns(self):
        agents = [dict(BREAKER_AGENTS[0], adapterType="other_local")]
        d = self.decide(agents=agents)
        self.assertTrue(any("other_local" in w and "default" in w for w in d.warnings))

    def test_unconfigured_live_agent_still_counts_toward_the_adapter_total(self):
        agents = BREAKER_AGENTS + [{"id": "a-stray", "name": "Unlisted", "status": "idle",
                                    "adapterType": "claude_local"}]
        runs = [run("a-stray", "2026-09-26T01:00:00Z"), run("a-stray", "2026-09-26T02:00:00Z"),
                run("a-stray", "2026-09-26T03:00:00Z")]
        d = self.decide(runs=runs, agents=agents)
        self.assertIn("/api/agents/a-stray/pause", [a.path for a in d.actions])


class ZeroRunCapTests(unittest.TestCase):
    """A cap of `0` reads as "no cap configured" at every enforcement site,
    because each one guards on truthiness (`if aid is None or not cap`, `if
    agent_cap and ...`, `if total_cap and ...`). Left unchecked it disables the
    breaker instead of stopping the agent, silently and with no warning. So the
    caps are validated before they are read: a `0`, a `"60"`, a `60.0`, a
    negative, or a `True` is a clear error, not a quiet no-op. `bool` is an
    `int` in Python, hence the explicit exclusion."""

    def cfg(self, **caps):
        return {**BREAKER_CFG, "runCaps": {"claude_local": caps, "default": {"harnessTotal": 1}}}

    def test_a_zero_per_agent_cap_raises_rather_than_disabling_the_breaker(self):
        with self.assertRaises(wd.PaperclipError) as ctx:
            wd.decide(self.cfg(agents={"scoper": 0}, harnessTotal=3), [], [], BREAKER_AGENTS, set(), LABEL, NOW)
        self.assertIn("scoper", str(ctx.exception))
        self.assertIn("0", str(ctx.exception))

    def test_a_zero_harness_total_raises(self):
        with self.assertRaises(wd.PaperclipError) as ctx:
            wd.decide(self.cfg(agents={"scoper": 2}, harnessTotal=0), [], [], BREAKER_AGENTS, set(), LABEL, NOW)
        self.assertIn("harnessTotal", str(ctx.exception))

    def test_a_zero_runs_per_day_raises(self):
        cfg = {**BREAKER_CFG, "agents": [dict(BREAKER_CFG["agents"][0], runsPerDay=0)]}
        with self.assertRaises(wd.PaperclipError) as ctx:
            wd.decide(cfg, [], [], BREAKER_AGENTS, set(), LABEL, NOW)
        self.assertIn("runsPerDay", str(ctx.exception))

    def test_a_string_a_float_a_negative_and_a_bool_are_each_refused(self):
        for bad in ("60", 60.0, -1, True):
            with self.subTest(cap=bad):
                with self.assertRaises(wd.PaperclipError):
                    wd.decide(self.cfg(agents={"scoper": bad}, harnessTotal=3), [], [], BREAKER_AGENTS,
                              set(), LABEL, NOW)

    def test_a_positive_whole_cap_passes(self):
        wd.validate_run_caps(self.cfg(agents={"scoper": 1}, harnessTotal=1))

    def test_an_absent_cap_is_not_a_zero_cap(self):
        """An agent with no `runsPerDay`, or an adapter entry with no `agents`
        block, is uncapped on purpose and stays legal. Only a cap written as
        `0` is refused, because that reads as a cap and enforces nothing."""
        wd.validate_run_caps({**BREAKER_CFG, "runCaps": {"claude_local": {"harnessTotal": 5},
                                                         "default": {"harnessTotal": 1}}})
        wd.validate_run_caps({"agents": [{"key": "x", "name": "X"}]})

    def test_the_caution_is_written_where_the_code_enforces_it(self):
        """The lesson has to survive the next edit, so it is a comment at the
        enforcement site, not only a test name."""
        text = (SCRIPTS / "paperclip-watchdog.py").read_text()
        self.assertIn("no cap configured", text)
        self.assertIn("never resumes on its own", text)


class AuthBurstTests(unittest.TestCase):
    def test_burst_of_auth_failures_pauses_every_agent_once(self):
        err = "Internal error: Failed to authenticate: OAuth session expired and could not be refreshed"
        runs = [run("a-scoper", "2026-09-26T14:50:00Z", "failed", err)] * 3
        d = decide(runs=runs)
        paths = sorted(a.path for a in d.actions)
        self.assertEqual(paths, ["/api/agents/a-research/pause", "/api/agents/a-scoper/pause"])

    def test_old_auth_failures_are_ignored(self):
        err = "OAuth session expired"
        runs = [run("a-scoper", "2026-09-25T20:00:00Z", "failed", err)] * 3
        self.assertEqual(decide(runs=runs).actions, [])

    # No `runsPerDay` here, so only the burst rule can act and a per-day cap
    # never confuses the result.
    UNCAPPED = {**CFG, "agents": [{k: v for k, v in a.items() if k != "runsPerDay"}
                                  for a in CFG["agents"]]}

    def burst(self, runs):
        return wd.decide(self.UNCAPPED, list(runs), [], AGENTS, set(), LABEL, NOW)

    def test_a_burst_one_short_of_the_threshold_pauses_nobody(self):
        err = "OAuth session expired"
        self.assertEqual(self.burst([run("a-scoper", "2026-09-26T14:50:00Z", "failed", err)] * 2).actions, [])

    def test_the_threshold_itself_pauses(self):
        err = "OAuth session expired"
        d = self.burst([run("a-scoper", "2026-09-26T14:50:00Z", "failed", err)] * 3)
        self.assertEqual(sorted(a.path for a in d.actions),
                         ["/api/agents/a-research/pause", "/api/agents/a-scoper/pause"])

    def test_a_failure_that_is_not_an_auth_failure_does_not_count(self):
        runs = [run("a-scoper", "2026-09-26T14:50:00Z", "failed", "some other failure")] * 3
        self.assertEqual(self.burst(runs).actions, [])

    def test_a_succeeded_run_carrying_the_pattern_does_not_count(self):
        err = "OAuth session expired"
        runs = [run("a-scoper", "2026-09-26T14:50:00Z", "succeeded", err)] * 3
        self.assertEqual(self.burst(runs).actions, [])


class ScopeCreepTests(unittest.TestCase):
    def test_agent_created_todo_issue_is_parked_in_backlog(self):
        d = decide(issues=[issue("i1", assigneeAgentId="a-research")])
        self.assertEqual(len(d.actions), 1)
        act = d.actions[0]
        self.assertEqual((act.method, act.path), ("PATCH", "/api/issues/i1"))
        self.assertEqual(act.body["status"], "backlog")
        self.assertIsNone(act.body["assigneeAgentId"])
        self.assertEqual(act.body["labelIds"], [LABEL])
        self.assertIn("i1", d.seen)

    def test_correct_filing_is_left_alone_and_marked_seen(self):
        d = decide(issues=[issue("i2", status="backlog", labelIds=[LABEL])])
        self.assertEqual(d.actions, [])
        self.assertIn("i2", d.seen)

    def test_backlog_filing_without_label_gets_the_label(self):
        d = decide(issues=[issue("i3", status="backlog", labelIds=["other"])])
        self.assertEqual(d.actions[0].body, {"labelIds": ["other", LABEL]})

    def test_a_person_created_issue_is_never_touched(self):
        d = decide(issues=[issue("i4", createdByUserId="local-board", createdByAgentId=None,
                                 assigneeAgentId="a-scoper")])
        self.assertEqual(d.actions, [])

    def test_routine_issue_is_never_touched(self):
        d = decide(issues=[issue("i5", originKind="routine_execution", createdByAgentId=None)])
        self.assertEqual(d.actions, [])

    def test_seen_issue_is_never_touched_again(self):
        d = decide(issues=[issue("i6", assigneeAgentId="a-research")], seen={"i6"})
        self.assertEqual(d.actions, [])

    def test_closed_agent_issue_is_marked_seen_without_action(self):
        d = decide(issues=[issue("i7", status="done")])
        self.assertEqual(d.actions, [])
        self.assertIn("i7", d.seen)

    def test_system_created_issue_is_parked(self):
        d = decide(issues=[issue("i8", createdByAgentId=None, originKind="productivity_review",
                                 assigneeAgentId="a-scoper")])
        self.assertEqual(d.actions[0].body["status"], "backlog")


def assigned(to, actor_type, actor):
    return {"action": "issue.updated", "actorType": actor_type, "actorId": actor,
            "details": {"changes": {"assigneeAgentId": {"from": None, "to": to}}}}


class GateTests(unittest.TestCase):
    def gate(self, events, status="todo"):
        iss = issue("t1", createdByUserId="local-board", createdByAgentId=None,
                    assigneeAgentId="a-research", status=status)
        return wd.decide(CFG, [], [iss], AGENTS, set(), LABEL, NOW, {"t1": events})

    def test_agent_assignment_is_sent_back_and_the_assigner_paused(self):
        d = self.gate([assigned("a-research", "agent", "a-scoper")])
        by_path = {a.path: a for a in d.actions}
        body = by_path["/api/issues/t1"].body
        self.assertEqual((body["status"], body["assigneeAgentId"], body["assigneeUserId"]),
                         ("in_review", None, "local-board"))
        self.assertIn("/api/agents/a-scoper/pause", by_path)

    def test_board_assignment_passes(self):
        self.assertEqual(self.gate([assigned("a-research", "user", "local-board")]).actions, [])

    def test_latest_assignment_decides(self):
        events = [assigned("a-research", "user", "local-board"), assigned("a-research", "agent", "a-scoper")]
        self.assertEqual(self.gate(events).actions, [])

    def test_closed_or_review_issue_is_not_checked(self):
        self.assertEqual(self.gate([assigned("a-research", "agent", "a-scoper")], status="in_review").actions, [])

    def test_agent_made_issue_handed_to_an_agent_gets_one_patch(self):
        iss = issue("t2", assigneeAgentId="a-research", status="todo")
        d = wd.decide(CFG, [], [iss], AGENTS, set(), LABEL, NOW,
                      {"t2": [assigned("a-research", "agent", "a-scoper")]})
        patches = [a for a in d.actions if a.path == "/api/issues/t2"]
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0].body["status"], "backlog")
        self.assertIn("without board approval", patches[0].body["comment"])
        self.assertIn("/api/agents/a-scoper/pause", [a.path for a in d.actions])

    def test_candidates_are_open_agent_held_issues(self):
        issues = [issue("x", assigneeAgentId="a", status="todo"), issue("y", status="todo"),
                  issue("z", assigneeAgentId="a", status="done")]
        self.assertEqual([i["id"] for i in wd.gate_candidates(issues)], ["x"])


def card(id_, status, revision="rev1", reason=None, resolved="2026-09-26T14:00:00Z"):
    result = {"version": 1, "outcome": status}
    if reason:
        result["reason"] = reason
    return {"id": id_, "kind": "request_confirmation", "status": status,
            "createdAt": "2026-09-26T13:00:00Z", "resolvedAt": None if status == "pending" else resolved,
            "result": None if status == "pending" else result,
            "payload": {"target": {"type": "issue_document", "key": "scope", "revisionId": revision}}}


def scope_doc(body="- Lead: research\n", revision="rev1"):
    return {"key": "scope", "body": body, "latestRevisionId": revision}


class ApprovalTests(unittest.TestCase):
    def waiting(self, **over):
        base = dict(status="in_review", createdByUserId="local-board", createdByAgentId=None,
                    assigneeUserId="local-board", executionPolicy=None)
        base.update(over)
        return issue("s1", **base)

    def run_(self, cards, docs=None, seen=(), iss=None):
        return wd.decide(CFG, [], [iss or self.waiting()], AGENTS, set(seen), LABEL, NOW, {},
                         {"s1": cards}, {"s1": docs if docs is not None else [scope_doc()]})

    def patches(self, d):
        return [a for a in d.actions if a.path == "/api/issues/s1"]

    def test_accepted_scope_starts_the_named_lead_with_a_board_stage(self):
        d = self.run_([card("x1", "accepted")])
        [a] = self.patches(d)
        self.assertEqual((a.body["status"], a.body["assigneeAgentId"], a.body["assigneeUserId"]),
                         ("todo", "a-research", None))
        stage = a.body["executionPolicy"]["stages"][0]
        self.assertEqual(stage["type"], "approval")
        self.assertEqual(stage["participants"], [{"type": "user", "userId": "local-board"}])
        self.assertIn("ix:x1", d.seen)

    def test_rejected_scope_returns_to_the_scoping_agent_with_the_reason(self):
        [a] = self.patches(self.run_([card("x1", "rejected", reason="Narrow it.")]))
        self.assertEqual((a.body["status"], a.body["assigneeAgentId"]), ("todo", "a-scoper"))
        self.assertIn("Narrow it.", a.body["comment"])

    def test_comment_that_supersedes_the_card_returns_to_the_scoping_agent(self):
        c = card("x1", "superseded_by_comment")
        c["status"] = "expired"
        [a] = self.patches(self.run_([c]))
        self.assertEqual(a.body["assigneeAgentId"], "a-scoper")
        self.assertIn("latest comment", a.body["comment"])

    def test_a_rejection_with_no_scoping_agent_configured_holds(self):
        cfg = {**CFG, "watchdog": {**CFG["watchdog"], "scopeAgent": "nobody"}}
        d = wd.decide(cfg, [], [self.waiting()], AGENTS, set(), LABEL, NOW, {},
                      {"s1": [card("x1", "rejected")]}, {"s1": [scope_doc()]})
        [a] = [x for x in d.actions if x.path == "/api/issues/s1"]
        self.assertIn("scoping agent is not", a.body["comment"])
        self.assertNotIn("assigneeAgentId", a.body)

    def test_newest_resolved_card_decides(self):
        cards = [card("old", "rejected", resolved="2026-09-26T10:00:00Z"), card("new", "accepted")]
        [a] = self.patches(self.run_(cards))
        self.assertEqual(a.body["assigneeAgentId"], "a-research")

    def test_pending_card_waits(self):
        self.assertEqual(self.patches(self.run_([card("x1", "accepted"), card("x2", "pending")])), [])

    def test_card_already_acted_on_is_skipped(self):
        self.assertEqual(self.patches(self.run_([card("x1", "accepted")], seen={"ix:x1"})), [])

    def test_stale_revision_holds_with_a_note(self):
        [a] = self.patches(self.run_([card("x1", "accepted", revision="rev1")], [scope_doc(revision="rev2")]))
        self.assertNotIn("assigneeAgentId", a.body)
        self.assertIn("changed after", a.body["comment"])

    def test_unknown_or_missing_lead_holds(self):
        for body in ("- Lead: marketing\n", "no lead here"):
            [a] = self.patches(self.run_([card("x1", "accepted")], [scope_doc(body)]))
            self.assertNotIn("status", a.body)
            self.assertIn("names no lead", a.body["comment"])

    def test_hold_is_not_repeated_but_a_fixed_cause_goes_through(self):
        docs = [scope_doc("- Lead: marketing\n")]
        first = self.run_([card("x1", "accepted")], docs)
        [_] = self.patches(first)
        self.assertEqual(self.patches(self.run_([card("x1", "accepted")], docs, seen=first.seen)), [])
        [b] = self.patches(self.run_([card("x1", "accepted")], seen=first.seen))
        self.assertEqual(b.body["assigneeAgentId"], "a-research")

    def test_agent_made_issue_is_parked_not_started(self):
        iss = self.waiting(createdByUserId=None, createdByAgentId="a-scoper")
        d = self.run_([card("x1", "accepted")], iss=iss)
        [a] = self.patches(d)
        self.assertEqual(a.body["status"], "backlog")
        self.assertNotIn("ix:x1", d.seen)

    def test_card_without_a_revision_holds(self):
        c = card("x1", "accepted")
        del c["payload"]["target"]["revisionId"]
        [a] = self.patches(self.run_([c]))
        self.assertIn("names no scope revision", a.body["comment"])

    def untargeted(self, id_="x1", status="accepted"):
        c = card(id_, status)
        del c["payload"]["target"]
        c["idempotencyKey"] = "scope:s1:rev1"
        return c

    def test_accepted_card_without_a_target_holds_and_warns(self):
        d = self.run_([self.untargeted()])
        [a] = self.patches(d)
        self.assertNotIn("assigneeAgentId", a.body)
        self.assertIn("no target", a.body["comment"])
        self.assertIn("ix:x1:hold:no-target", d.seen)
        self.assertTrue(any("x1" in w and "no target" in w for w in d.warnings))

    def test_card_without_a_target_is_held_once(self):
        first = self.run_([self.untargeted()])
        again = self.run_([self.untargeted()], seen=first.seen)
        self.assertEqual(self.patches(again), [])
        self.assertEqual(again.warnings, [])

    def test_pending_card_without_a_target_waits(self):
        d = self.run_([self.untargeted(status="pending")])
        self.assertEqual((self.patches(d), d.warnings), ([], []))

    def test_other_untargeted_confirmations_are_ignored(self):
        c = self.untargeted()
        c["idempotencyKey"] = "confirmation:s1:plan:rev1"
        d = self.run_([c])
        self.assertEqual((self.patches(d), d.warnings), ([], []))

    def test_unknown_outcome_is_warned(self):
        c = card("x1", "accepted")
        c["status"], c["result"] = "expired", {"outcome": "issue_closed"}
        d = self.run_([c])
        self.assertEqual(self.patches(d), [])
        self.assertTrue(any("issue_closed" in w for w in d.warnings))

    def test_one_failed_fetch_skips_only_that_issue(self):
        class Half:
            def get(self, path):
                if "bad" in path:
                    raise wd.PaperclipError("404")
                return []

        lines = []
        out = wd._fetch_each(Half(), ["good", "bad"], "activity", lines, "T")
        self.assertEqual(out, {"good": []})
        self.assertTrue(any("bad" in line for line in lines))

    def test_policies_come_from_the_issue_route(self):
        # The company issue list returns executionPolicy as null even when a
        # stage is set, so a delivery under review looked like a waiting scope.
        staged = {"stages": [{"type": "approval"}]}

        class Detail:
            def get(self, path):
                if "bad" in path:
                    raise wd.PaperclipError("500")
                return {"executionPolicy": staged if "staged" in path else None}

        listed = [self.waiting(id="staged"), self.waiting(id="plain"), self.waiting(id="bad"),
                  issue("other", status="todo", executionPolicy=None)]
        lines = []
        out = wd.attach_policies(Detail(), listed, "local-board", lines, "T")
        self.assertEqual([i["id"] for i in wd.approval_candidates(out)], ["plain"])
        self.assertTrue(any("bad" in line for line in lines))

    def test_missing_scope_document_holds(self):
        [a] = self.patches(self.run_([card("x1", "accepted")], []))
        self.assertIn("missing", a.body["comment"])

    def test_delivery_under_a_stage_is_left_to_the_server(self):
        iss = self.waiting(executionPolicy={"stages": [{"type": "approval"}]})
        self.assertEqual(self.patches(self.run_([card("x1", "accepted")], iss=iss)), [])

    def test_other_confirmations_are_ignored(self):
        other = card("x1", "accepted")
        other["payload"]["target"]["key"] = "plan"
        self.assertEqual(self.patches(self.run_([other])), [])

    def test_failed_start_leaves_the_card_to_retry(self):
        class Boom:
            def send(self, method, path, body=None):
                raise wd.PaperclipError("500")

        d = self.run_([card("x1", "accepted")])
        _, seen, failed = wd.execute(d, Boom(), dry_run=False, stamp="T")
        self.assertEqual(failed, 1)
        self.assertNotIn("ix:x1", seen)

    def test_lead_line_forms(self):
        for body, want in (("- Lead: research", "research"), ("**Lead:** engineering", "engineering"),
                           ("Lead: `Research`", "research"), ("- Leadership: x", None)):
            self.assertEqual(wd.parse_lead(body), want, body)


WORKER_CFG = {
    "companyId": "c1",
    "agents": [
        {"key": "scoper", "id": "a-scoper", "name": "Scoper"},
        {"key": "research-worker-1", "id": "a-rw1", "name": "Research worker 1"},
        {"key": "research-worker-2", "id": "a-rw2", "name": "Research worker 2"},
    ],
    "watchdog": {"authFailureBurst": 3, "authFailurePattern": "OAuth session expired",
                 "workerKeys": ["research-worker-1", "research-worker-2"]},
}

WORKER_AGENTS = [
    {"id": "a-scoper", "name": "Scoper", "status": "idle"},
    {"id": "a-rw1", "name": "Research worker 1", "status": "idle"},
    {"id": "a-rw2", "name": "Research worker 2", "status": "idle"},
]


class WorkerIssueGuardTests(unittest.TestCase):
    """A worker that creates an issue is paused, the same way a run-cap breach
    pauses an agent. A lead is never listed in `workerKeys`, because a lead
    creating child issues is the delegation flow working as designed."""

    def decide(self, issues, cfg=WORKER_CFG, agents=WORKER_AGENTS):
        return wd.decide(cfg, [], list(issues), list(agents), set(), LABEL, NOW)

    def test_worker_created_issue_pauses_the_worker(self):
        d = self.decide([issue("i1", createdByAgentId="a-rw1", status="todo")])
        self.assertIn(("POST", "/api/agents/a-rw1/pause"), [(a.method, a.path) for a in d.actions])

    def test_worker_created_backlog_filing_with_no_assignee_does_not_pause(self):
        d = self.decide([issue("i1", createdByAgentId="a-rw1", status="backlog")])
        self.assertNotIn("/api/agents/a-rw1/pause", [a.path for a in d.actions])

    def test_worker_created_backlog_issue_with_an_assignee_still_pauses(self):
        d = self.decide([issue("i1", createdByAgentId="a-rw1", status="backlog", assigneeAgentId="a-rw1")])
        self.assertIn("/api/agents/a-rw1/pause", [a.path for a in d.actions])

    def test_non_worker_creator_is_not_guarded(self):
        d = self.decide([issue("i1", createdByAgentId="a-scoper", status="todo")])
        self.assertNotIn("/api/agents/a-scoper/pause", [a.path for a in d.actions])

    def test_already_paused_worker_is_not_paused_again(self):
        agents = [dict(a) for a in WORKER_AGENTS]
        agents[1]["status"] = "paused"
        d = self.decide([issue("i1", createdByAgentId="a-rw1", status="todo")], agents=agents)
        self.assertEqual([a.path for a in d.actions if a.method == "POST"], [])

    def test_no_worker_keys_configured_changes_nothing(self):
        cfg = {**WORKER_CFG, "watchdog": {**WORKER_CFG["watchdog"], "workerKeys": []}}
        d = self.decide([issue("i1", createdByAgentId="a-rw1", status="todo")], cfg=cfg)
        self.assertEqual([a.path for a in d.actions if a.method == "POST"], [])

    def test_worker_with_no_live_agent_warns(self):
        cfg = {**WORKER_CFG, "agents": WORKER_CFG["agents"] + [
            {"key": "research-worker-3", "id": None, "name": "Research worker 3"}]}
        cfg["watchdog"] = {**cfg["watchdog"], "workerKeys": cfg["watchdog"]["workerKeys"] + ["research-worker-3"]}
        d = self.decide([], cfg=cfg, agents=WORKER_AGENTS)
        self.assertTrue(any("Research worker 3" in w for w in d.warnings))

    def test_two_worker_created_issues_pause_each_worker_once(self):
        d = self.decide([issue("i1", createdByAgentId="a-rw1", status="todo"),
                         issue("i2", createdByAgentId="a-rw1", status="in_progress"),
                         issue("i3", createdByAgentId="a-rw2", status="todo")])
        paths = sorted(a.path for a in d.actions if a.method == "POST")
        self.assertEqual(paths, ["/api/agents/a-rw1/pause", "/api/agents/a-rw2/pause"])

    def test_park_still_files_the_worker_issue_as_scope_creep(self):
        d = self.decide([issue("i1", createdByAgentId="a-rw1", status="todo")])
        parks = [a for a in d.actions if a.path == "/api/issues/i1"]
        self.assertEqual(len(parks), 1)
        self.assertEqual(parks[0].body["status"], "backlog")

    def test_later_reassignment_of_an_already_judged_filing_does_not_pause_the_worker(self):
        # Pass 1: the worker files a compliant backlog issue with no assignee.
        # _park judges it (marks it seen) even though it takes no pausing
        # action. Pass 2: someone else assigns and starts it. Because it is
        # already judged, _worker_pauses must not re-read its now different
        # state and retroactively pause the worker for it.
        compliant = issue("i1", createdByAgentId="a-rw1", status="backlog")
        first = wd.decide(WORKER_CFG, [], [compliant], WORKER_AGENTS, set(), LABEL, NOW)
        self.assertEqual([a for a in first.actions if a.method == "POST"], [])
        self.assertIn("i1", first.seen)
        reassigned = issue("i1", createdByAgentId="a-rw1", status="in_progress", assigneeAgentId="a-scoper")
        second = wd.decide(WORKER_CFG, [], [reassigned], WORKER_AGENTS, first.seen, LABEL, NOW)
        self.assertEqual([a for a in second.actions if a.method == "POST"], [])


DELEGATION_CFG = {
    "companyId": "c1",
    "agents": [
        {"key": "scoper", "id": "a-scoper", "name": "Scoper"},
        {"key": "research", "id": "a-research", "name": "Research lead", "reportsTo": "scoper"},
        {"key": "research-worker-1", "id": "a-rw1", "name": "Research worker 1", "reportsTo": "research"},
        {"key": "engineering", "id": "a-eng", "name": "Engineering lead", "reportsTo": "scoper"},
    ],
    "watchdog": {"authFailureBurst": 3, "authFailurePattern": "OAuth session expired",
                 "leadKeys": ["research", "engineering", "knowledge-office"]},
}

DELEGATION_AGENTS = [
    {"id": "a-scoper", "name": "Scoper", "status": "idle"},
    {"id": "a-research", "name": "Research lead", "status": "idle"},
    {"id": "a-rw1", "name": "Research worker 1", "status": "idle"},
    {"id": "a-eng", "name": "Engineering lead", "status": "idle"},
]


class DelegationGuardTests(unittest.TestCase):
    """A lead splits its approved scope into child issues assigned to its own
    reports. Neither the approval gate nor the scope-creep park may treat that
    as a violation, and the lead making the child must not be paused for it."""

    def decide(self, issues, events, cfg=DELEGATION_CFG, agents=DELEGATION_AGENTS):
        return wd.decide(cfg, [], list(issues), list(agents), set(), LABEL, NOW, events)

    def ticket(self, **over):
        base = dict(assigneeAgentId="a-research", status="in_progress",
                    createdByUserId="local-board", createdByAgentId=None)
        base.update(over)
        return issue("ticket-1", **base)

    def test_lead_delegated_child_passes_untouched_and_the_lead_is_not_paused(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-rw1", status="todo",
                      createdByAgentId="a-research")
        events = {"child-1": [assigned("a-rw1", "agent", "a-research")]}
        d = self.decide([self.ticket(), child], events)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.warnings, [])

    def test_assignee_who_does_not_report_to_the_lead_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-scoper", status="todo",
                      createdByAgentId="a-research")
        events = {"child-1": [assigned("a-scoper", "agent", "a-research")]}
        d = self.decide([self.ticket(), child], events)
        paths = [a.path for a in d.actions]
        self.assertIn("/api/issues/child-1", paths)
        self.assertIn("/api/agents/a-research/pause", paths)

    def test_parent_ticket_not_held_by_the_lead_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-rw1", status="todo",
                      createdByAgentId="a-research")
        events = {"child-1": [assigned("a-rw1", "agent", "a-research")]}
        d = self.decide([self.ticket(assigneeAgentId="a-eng"), child], events)
        self.assertIn("/api/issues/child-1", [a.path for a in d.actions])

    def test_cross_lead_delegation_gets_todays_treatment(self):
        # The engineering lead's ticket delegating to a research worker: the
        # worker reports to the research lead, so the two edges do not chain.
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-rw1", status="todo",
                      createdByAgentId="a-eng")
        events = {"child-1": [assigned("a-rw1", "agent", "a-eng")]}
        d = self.decide([self.ticket(assigneeAgentId="a-eng"), child], events)
        self.assertIn("/api/issues/child-1", [a.path for a in d.actions])

    def test_no_parent_issue_gets_todays_treatment(self):
        child = issue("child-1", assigneeAgentId="a-rw1", status="todo", createdByAgentId="a-research")
        events = {"child-1": [assigned("a-rw1", "agent", "a-research")]}
        d = self.decide([child], events)
        self.assertIn("/api/issues/child-1", [a.path for a in d.actions])

    def test_no_lead_keys_configured_is_todays_behavior(self):
        cfg = {**DELEGATION_CFG, "watchdog": {**DELEGATION_CFG["watchdog"], "leadKeys": []}}
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-rw1", status="todo",
                      createdByAgentId="a-research")
        events = {"child-1": [assigned("a-rw1", "agent", "a-research")]}
        d = self.decide([self.ticket(), child], events, cfg=cfg)
        paths = [a.path for a in d.actions]
        self.assertIn("/api/issues/child-1", paths)
        self.assertIn("/api/agents/a-research/pause", paths)

    def test_third_party_lead_assigning_into_another_leads_hierarchy_gets_todays_treatment(self):
        # The engineering lead assigns a child under the research lead's ticket
        # to a research worker. Structurally this looks like the research lead's
        # own delegation, but the engineering lead made the assignment: the
        # shape checks alone are not enough, the actor must be the lead too.
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-rw1", status="todo",
                      createdByAgentId="a-eng")
        events = {"child-1": [assigned("a-rw1", "agent", "a-eng")]}
        d = self.decide([self.ticket(), child], events)
        paths = [a.path for a in d.actions]
        self.assertIn("/api/issues/child-1", paths)
        self.assertIn("/api/agents/a-eng/pause", paths)

    def test_unclassified_agent_assigning_into_a_leads_hierarchy_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-rw1", status="todo",
                      createdByAgentId="a-stray")
        events = {"child-1": [assigned("a-rw1", "agent", "a-stray")]}
        agents = DELEGATION_AGENTS + [{"id": "a-stray", "name": "Unlisted", "status": "idle"}]
        d = self.decide([self.ticket(), child], events, agents=agents)
        paths = [a.path for a in d.actions]
        self.assertIn("/api/issues/child-1", paths)
        self.assertIn("/api/agents/a-stray/pause", paths)


class IsDelegatedChildTests(unittest.TestCase):
    REPORTS_TO = {"scoper": None, "research": "scoper", "research-worker-1": "research", "engineering": "scoper"}

    def test_true_when_both_edges_hold_and_actor_is_the_lead(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-rw1": "research-worker-1"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-rw1"}
        self.assertTrue(wd._is_delegated_child(DELEGATION_CFG, child, by_id, id_to_key, self.REPORTS_TO, "research"))

    def test_false_when_actor_is_not_the_lead(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-rw1": "research-worker-1", "a-eng": "engineering"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-rw1"}
        self.assertFalse(wd._is_delegated_child(DELEGATION_CFG, child, by_id, id_to_key, self.REPORTS_TO,
                                                "engineering"))

    def test_false_when_actor_is_unclassified(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-rw1": "research-worker-1"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-rw1"}
        self.assertFalse(wd._is_delegated_child(DELEGATION_CFG, child, by_id, id_to_key, self.REPORTS_TO, None))

    def test_false_with_no_parent(self):
        child = {"assigneeAgentId": "a-rw1"}
        self.assertFalse(wd._is_delegated_child(DELEGATION_CFG, child, {}, {}, self.REPORTS_TO, "research"))

    def test_false_when_parent_is_unknown(self):
        child = {"parentId": "ghost", "assigneeAgentId": "a-rw1"}
        self.assertFalse(wd._is_delegated_child(DELEGATION_CFG, child, {}, {"a-rw1": "research-worker-1"},
                                                self.REPORTS_TO, "research"))

    def test_false_when_child_has_no_assignee(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        child = {"parentId": "ticket-1"}
        self.assertFalse(wd._is_delegated_child(DELEGATION_CFG, child, by_id, {"a-research": "research"},
                                                self.REPORTS_TO, "research"))


WIKI_CFG = {
    "companyId": "c1",
    "agents": DELEGATION_CFG["agents"] + [
        {"key": "knowledge-office", "id": "a-knowledge", "name": "Knowledge office", "reportsTo": "scoper"},
    ],
    "watchdog": DELEGATION_CFG["watchdog"],
}

WIKI_AGENTS = DELEGATION_AGENTS + [{"id": "a-knowledge", "name": "Knowledge office", "status": "idle"}]
WIKI_LABEL = "label-wiki-request"


class WikiRequestGuardTests(unittest.TestCase):
    """A lead files a `wiki-request` child to the knowledge office, which
    reports to the scoping agent rather than to any lead, so the `reportsTo`
    chain the first exemption walks never reaches it. Neither the gate nor the
    park may treat that as a violation, and the lead is not paused for it."""

    def ticket(self, **over):
        base = dict(assigneeAgentId="a-research", status="in_progress",
                    createdByUserId="local-board", createdByAgentId=None)
        base.update(over)
        return issue("ticket-1", **base)

    def decide(self, issues, events, wiki_label=WIKI_LABEL, cfg=WIKI_CFG, agents=WIKI_AGENTS):
        return wd.decide(cfg, [], list(issues), list(agents), set(), LABEL, NOW, events,
                         wiki_request_label_id=wiki_label)

    def test_wiki_request_child_passes_untouched_and_the_lead_is_not_paused(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-knowledge", status="todo",
                      createdByAgentId="a-research", labelIds=[WIKI_LABEL])
        events = {"child-1": [assigned("a-knowledge", "agent", "a-research")]}
        d = self.decide([self.ticket(), child], events)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.warnings, [])

    def test_missing_wiki_request_label_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-knowledge", status="todo",
                      createdByAgentId="a-research")
        events = {"child-1": [assigned("a-knowledge", "agent", "a-research")]}
        d = self.decide([self.ticket(), child], events)
        self.assertIn("/api/issues/child-1", [a.path for a in d.actions])

    def test_another_assignee_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-eng", status="todo",
                      createdByAgentId="a-research", labelIds=[WIKI_LABEL])
        events = {"child-1": [assigned("a-eng", "agent", "a-research")]}
        d = self.decide([self.ticket(), child], events)
        self.assertIn("/api/issues/child-1", [a.path for a in d.actions])

    def test_parent_not_held_by_a_lead_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-knowledge", status="todo",
                      createdByAgentId="a-research", labelIds=[WIKI_LABEL])
        events = {"child-1": [assigned("a-knowledge", "agent", "a-research")]}
        d = self.decide([self.ticket(assigneeAgentId="a-scoper"), child], events)
        self.assertIn("/api/issues/child-1", [a.path for a in d.actions])

    def test_no_wiki_label_configured_is_todays_behavior(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-knowledge", status="todo",
                      createdByAgentId="a-research", labelIds=[WIKI_LABEL])
        events = {"child-1": [assigned("a-knowledge", "agent", "a-research")]}
        d = self.decide([self.ticket(), child], events, wiki_label=None)
        self.assertIn("/api/issues/child-1", [a.path for a in d.actions])

    def test_third_party_lead_filing_into_another_leads_hierarchy_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-knowledge", status="todo",
                      createdByAgentId="a-eng", labelIds=[WIKI_LABEL])
        events = {"child-1": [assigned("a-knowledge", "agent", "a-eng")]}
        d = self.decide([self.ticket(), child], events)
        paths = [a.path for a in d.actions]
        self.assertIn("/api/issues/child-1", paths)
        self.assertIn("/api/agents/a-eng/pause", paths)

    def test_unclassified_agent_filing_a_wiki_request_gets_todays_treatment(self):
        child = issue("child-1", parentId="ticket-1", assigneeAgentId="a-knowledge", status="todo",
                      createdByAgentId="a-stray", labelIds=[WIKI_LABEL])
        events = {"child-1": [assigned("a-knowledge", "agent", "a-stray")]}
        agents = WIKI_AGENTS + [{"id": "a-stray", "name": "Unlisted", "status": "idle"}]
        d = self.decide([self.ticket(), child], events, agents=agents)
        paths = [a.path for a in d.actions]
        self.assertIn("/api/issues/child-1", paths)
        self.assertIn("/api/agents/a-stray/pause", paths)


class IsWikiRequestChildTests(unittest.TestCase):
    def test_true_when_all_three_hold_and_actor_is_the_lead(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-knowledge": "knowledge-office"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": ["wiki-lbl"]}
        self.assertTrue(wd._is_wiki_request_child(WIKI_CFG, child, by_id, id_to_key, "wiki-lbl", "research"))

    def test_false_when_actor_is_not_the_lead(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-knowledge": "knowledge-office", "a-eng": "engineering"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": ["wiki-lbl"]}
        self.assertFalse(wd._is_wiki_request_child(WIKI_CFG, child, by_id, id_to_key, "wiki-lbl", "engineering"))

    def test_false_when_actor_is_unclassified(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-knowledge": "knowledge-office"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": ["wiki-lbl"]}
        self.assertFalse(wd._is_wiki_request_child(WIKI_CFG, child, by_id, id_to_key, "wiki-lbl", None))

    def test_false_with_no_wiki_label_configured(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-knowledge": "knowledge-office"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": ["wiki-lbl"]}
        self.assertFalse(wd._is_wiki_request_child(WIKI_CFG, child, by_id, id_to_key, None, "research"))

    def test_false_without_the_label(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-knowledge": "knowledge-office"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": []}
        self.assertFalse(wd._is_wiki_request_child(WIKI_CFG, child, by_id, id_to_key, "wiki-lbl", "research"))

    def test_false_when_the_assignee_is_not_the_knowledge_office(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-rw1": "research-worker-1"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-rw1", "labelIds": ["wiki-lbl"]}
        self.assertFalse(wd._is_wiki_request_child(WIKI_CFG, child, by_id, id_to_key, "wiki-lbl", "research"))

    def test_false_when_parent_is_not_held_by_a_lead(self):
        by_id = {"ticket-1": {"assigneeAgentId": "a-scoper"}}
        id_to_key = {"a-scoper": "scoper", "a-knowledge": "knowledge-office"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": ["wiki-lbl"]}
        self.assertFalse(wd._is_wiki_request_child(WIKI_CFG, child, by_id, id_to_key, "wiki-lbl", "scoper"))

    def test_the_assignee_key_is_configurable(self):
        cfg = {**WIKI_CFG, "watchdog": {**WIKI_CFG["watchdog"], "wikiRequestAssigneeKey": "librarian"}}
        by_id = {"ticket-1": {"assigneeAgentId": "a-research"}}
        id_to_key = {"a-research": "research", "a-knowledge": "librarian"}
        child = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": ["wiki-lbl"]}
        self.assertTrue(wd._is_wiki_request_child(cfg, child, by_id, id_to_key, "wiki-lbl", "research"))

    KEYS = {"a-research": "research", "a-eng": "engineering", "a-scoper": "scoper",
            "a-knowledge": "knowledge-office"}
    CHILD = {"parentId": "ticket-1", "assigneeAgentId": "a-knowledge", "labelIds": ["wiki-lbl"],
             "originRunId": "run-1"}

    def handed_back_parent(self, status="in_review", user="local-board"):
        return {"ticket-1": {"id": "ticket-1", "assigneeAgentId": None, "assigneeUserId": user, "status": status}}

    def origin(self, agent="a-research", woke_for="ticket-1", as_text=False):
        snapshot = {"issueId": woke_for, "taskId": woke_for}
        return {"run-1": {"id": "run-1", "agentId": agent,
                          "contextSnapshot": json.dumps(snapshot) if as_text else snapshot}}

    def check(self, actor, parent=None, runs=None):
        return wd._is_wiki_request_child(WIKI_CFG, self.CHILD, parent or self.handed_back_parent(),
                                         self.KEYS, "wiki-lbl", actor, runs)

    def test_true_when_the_lead_handed_the_parent_back_and_filed_from_its_run(self):
        for status in ("in_review", "done"):
            for as_text in (False, True):
                with self.subTest(status=status, as_text=as_text):
                    self.assertTrue(self.check("research", self.handed_back_parent(status),
                                               self.origin(as_text=as_text)))

    def test_another_lead_cannot_use_a_handed_back_parent(self):
        self.assertFalse(self.check("engineering", runs=self.origin("a-eng", woke_for="ticket-9")))
        self.assertFalse(self.check("engineering", runs=self.origin("a-research")))

    def test_origin_run_woken_for_another_issue_fails(self):
        self.assertFalse(self.check("research", runs=self.origin(woke_for="ticket-9")))

    def test_unknown_or_unreadable_origin_run_fails(self):
        bad = {"run-1": {"id": "run-1", "agentId": "a-research", "contextSnapshot": "{not json"}}
        for runs in (None, {}, bad):
            with self.subTest(runs=runs):
                self.assertFalse(self.check("research", runs=runs))

    def test_handed_back_parent_still_needs_a_lead_as_actor(self):
        for actor, agent in (("scoper", "a-scoper"), (None, "a-research")):
            with self.subTest(actor=actor):
                self.assertFalse(self.check(actor, runs=self.origin(agent)))

    def test_unassigned_or_open_parent_is_not_handed_back(self):
        for parent in (self.handed_back_parent(user=None), self.handed_back_parent(status="todo")):
            with self.subTest(parent=parent):
                self.assertFalse(self.check("research", parent, self.origin()))


class RobustnessTests(unittest.TestCase):
    def test_bad_timestamp_counts_toward_the_cap(self):
        runs = [run("a-scoper", "2026-09-26T01:00:00Z"), {"agentId": "a-scoper", "createdAt": "not a date"}]
        d = decide(runs=runs)
        self.assertEqual([a.path for a in d.actions], ["/api/agents/a-scoper/pause"])

    def test_missing_timestamp_does_not_crash(self):
        d = decide(runs=[{"agentId": "a-research"}])
        self.assertEqual([a.path for a in d.actions], ["/api/agents/a-research/pause"])

    def test_unresolved_agent_is_warned(self):
        d = decide(agents=[AGENTS[0]])
        self.assertTrue(any("Research lead" in w for w in d.warnings))

    def test_failed_park_is_not_marked_seen(self):
        class Boom:
            def send(self, method, path, body=None):
                raise wd.PaperclipError("500")

        d = decide(issues=[issue("i9", assigneeAgentId="a-research")])
        lines, seen, failed = wd.execute(d, Boom(), dry_run=False, stamp="T")
        self.assertEqual(failed, 1)
        self.assertNotIn("i9", seen)
        self.assertTrue(any("failed: park" in line for line in lines))

    def test_state_file_round_trip_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            wd._save_seen(path, {"b", "a"})
            self.assertEqual(wd._load_seen(path), ({"a", "b"}, None))
            path.write_text("{truncated")
            seen, warning = wd._load_seen(path)
            self.assertEqual(seen, set())
            self.assertIn("unreadable", warning)

    def test_a_missing_state_file_starts_empty_without_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen, swaps, warning = wd._load_state(Path(tmp) / "nope.json")
        self.assertEqual((seen, swaps, warning), (set(), {}, None))

    def test_saving_state_is_atomic_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "state.json"
            wd._save_state(path, {"a"}, {"lead": {"twinKey": "t"}})
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["state.json"])
            self.assertEqual(json.loads(path.read_text()),
                             {"seenIssueIds": ["a"], "swaps": {"lead": {"twinKey": "t"}}})

    def test_a_dry_run_never_calls_the_server(self):
        class Boom:
            def send(self, *a, **k):
                raise AssertionError("a dry run must never call the server")

        d = decide(issues=[issue("i1", assigneeAgentId="a-research")])
        lines, seen, failed = wd.execute(d, Boom(), dry_run=True, stamp="T")
        self.assertEqual(failed, 0)
        self.assertTrue(any(line.startswith("T plan:") for line in lines))


class ParseTests(unittest.TestCase):
    def test_parse_accepts_z_and_offset(self):
        self.assertEqual(wd.parse_ts("2026-09-26T01:00:00.123Z").tzinfo, timezone.utc)
        self.assertEqual(wd.parse_ts("2026-09-26T01:00:00+00:00").hour, 1)


class StatePathTests(unittest.TestCase):
    def test_flag_wins(self):
        self.assertEqual(wd.state_path({"watchdog": {"stateFile": "x.json"}}, "/tmp/s.json"), Path("/tmp/s.json"))

    def test_config_names_the_state_file(self):
        self.assertEqual(wd.state_path({"watchdog": {"stateFile": ".paperclip/w2.json"}}, None),
                         wd.REPO_ROOT / ".paperclip" / "w2.json")

    def test_the_default_state_file(self):
        self.assertEqual(wd.state_path({}, None), wd.REPO_ROOT / ".paperclip" / "watchdog-state.json")


SWAP_CFG = {
    "companyId": "c1",
    "agents": [
        {"key": "scoper", "id": "a-scoper", "name": "Scoper"},
        {"key": "engineering", "id": "a-eng", "name": "Engineering lead"},
        {"key": "engineering-twin", "id": "a-standby", "name": "Engineering standby", "twinOf": "engineering"},
    ],
    "watchdog": {"authFailureBurst": 3, "authFailurePattern": "OAuth session expired"},
}

SWAP_AGENTS = [
    {"id": "a-scoper", "name": "Scoper", "status": "idle"},
    {"id": "a-eng", "name": "Engineering lead", "status": "idle"},
    {"id": "a-standby", "name": "Engineering standby", "status": "paused"},
]


class SwapOutTests(unittest.TestCase):
    """A lead with a twin and no active swap swaps out on two failed runs in a
    row. A failed run cannot tell quota exhaustion apart from any other
    terminal failure, so the failure count is the signal."""

    def decide(self, runs, issues=(), agents=SWAP_AGENTS, swaps=None, cfg=SWAP_CFG):
        return wd.decide(cfg, list(runs), list(issues), list(agents), set(), LABEL, NOW, swaps=swaps)

    def test_two_failed_runs_in_a_row_swap(self):
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        paths = {(a.method, a.path) for a in d.actions}
        self.assertIn(("POST", "/api/agents/a-standby/resume"), paths)
        self.assertIn(("POST", "/api/agents/a-eng/pause"), paths)
        self.assertIn("engineering", d.swaps)
        self.assertEqual(d.swaps["engineering"]["twinId"], "a-standby")
        self.assertEqual(d.swaps["engineering"]["leadId"], "a-eng")

    def test_one_failed_run_does_not_swap(self):
        runs = [run("a-eng", "2026-09-26T10:00:00Z", "succeeded"),
                run("a-eng", "2026-09-26T11:00:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, {})

    def test_a_success_between_two_failures_does_not_swap(self):
        runs = [run("a-eng", "2026-09-26T09:00:00Z", "failed", error_code="boom0"),
                run("a-eng", "2026-09-26T10:00:00Z", "succeeded"),
                run("a-eng", "2026-09-26T11:00:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, {})

    def test_two_failures_older_than_the_window_do_not_swap(self):
        # NOW is 2026-09-26T15:00:00Z. Both failures are hours old.
        runs = [run("a-eng", "2026-09-26T10:00:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T11:00:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, {})

    def test_one_failure_inside_the_window_and_one_outside_does_not_swap(self):
        runs = [run("a-eng", "2026-09-26T11:00:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, {})

    def test_a_failure_exactly_thirty_minutes_old_counts_as_inside_the_window(self):
        # NOW is 2026-09-26T15:00:00Z; 14:30:00Z is exactly SWAP_FAILURE_WINDOW old.
        runs = [run("a-eng", "2026-09-26T14:30:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T14:45:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertIn("engineering", d.swaps)

    def test_a_run_missing_its_timestamp_does_not_swap(self):
        runs = [{"agentId": "a-eng", "status": "failed", "errorCode": "boom1"},
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, {})

    def test_long_runs_that_just_failed_swap_on_their_finish_time(self):
        runs = [run("a-eng", "2026-09-26T13:55:00Z", "failed", error_code="boom1",
                    finished_at="2026-09-26T14:40:00Z"),
                run("a-eng", "2026-09-26T14:00:00Z", "failed", error_code="boom2",
                    finished_at="2026-09-26T14:55:00Z")]
        d = self.decide(runs)
        self.assertIn("engineering", d.swaps)

    def test_recent_starts_that_failed_long_ago_do_not_swap(self):
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error_code="boom1",
                    finished_at="2026-09-26T13:00:00Z"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2",
                    finished_at="2026-09-26T13:10:00Z")]
        d = self.decide(runs)
        self.assertEqual(d.swaps, {})

    def test_a_future_finish_time_is_outside_the_window(self):
        runs = [run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T16:00:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, {})

    def test_cancelled_interrupted_queued_and_running_runs_are_ignored(self):
        runs = [run("a-eng", "2026-09-26T14:35:00Z", "failed", error_code="boom0"),
                run("a-eng", "2026-09-26T14:36:00Z", "cancelled"),
                run("a-eng", "2026-09-26T14:37:00Z", "interrupted"),
                run("a-eng", "2026-09-26T14:38:00Z", "queued"),
                run("a-eng", "2026-09-26T14:39:00Z", "running"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)
        self.assertIn("engineering", d.swaps)

    def test_reassigns_the_leads_open_issues_with_one_comment_naming_both_agents(self):
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        issues = [issue("t1", assigneeAgentId="a-eng", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None),
                  issue("t2", assigneeAgentId="a-eng", status="done",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = self.decide(runs, issues=issues)
        patches = [a for a in d.actions if a.path == "/api/issues/t1"]
        self.assertEqual(len(patches), 1)
        patch = patches[0]
        self.assertEqual(patch.body["assigneeAgentId"], "a-standby")
        self.assertIn("Engineering lead", patch.body["comment"])
        self.assertIn("Engineering standby", patch.body["comment"])
        self.assertIn("boom1", patch.body["comment"])
        self.assertIn("boom2", patch.body["comment"])
        self.assertEqual(d.swaps["engineering"]["issueIds"], ["t1"])
        self.assertFalse(any(a.path == "/api/issues/t2" for a in d.actions))

    def test_no_double_swap_while_active(self):
        runs = [run("a-eng", "2026-09-26T10:00:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T11:00:00Z", "failed", error_code="boom2")]
        existing = {"engineering": {"twinKey": "engineering-twin", "leadId": "a-eng", "twinId": "a-standby",
                                    "startedAt": "2026-09-26T11:30:00+00:00", "issueIds": []}}
        agents = [dict(SWAP_AGENTS[0]), dict(SWAP_AGENTS[1], status="paused"), dict(SWAP_AGENTS[2], status="idle")]
        d = self.decide(runs, agents=agents, swaps=dict(existing))
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, existing)

    def test_no_twins_configured_changes_nothing(self):
        cfg = {"companyId": "c1", "agents": [{"key": "scoper", "id": "a-scoper", "name": "Scoper"}],
               "watchdog": {"authFailureBurst": 3, "authFailurePattern": "OAuth session expired"}}
        agents = [{"id": "a-scoper", "name": "Scoper", "status": "idle"}]
        runs = [run("a-scoper", "2026-09-26T10:00:00Z", "failed"), run("a-scoper", "2026-09-26T11:00:00Z", "failed")]
        d = wd.decide(cfg, runs, [], agents, set(), LABEL, NOW)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, {})

    def test_a_twin_pair_with_one_side_unmatched_warns_and_skips(self):
        agents = [dict(SWAP_AGENTS[0]), dict(SWAP_AGENTS[1])]
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        d = self.decide(runs, agents=agents)
        self.assertEqual(d.swaps, {})
        self.assertTrue(any("twin pair" in w for w in d.warnings))

    def test_dry_run_plans_the_swap_without_calling_the_server(self):
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        d = self.decide(runs)

        class Boom:
            def send(self, *a, **k):
                raise AssertionError("a dry run must never call the server")

        self.assertIn(("POST", "/api/agents/a-standby/resume"), [(a.method, a.path) for a in d.actions])
        self.assertIn(("POST", "/api/agents/a-eng/pause"), [(a.method, a.path) for a in d.actions])
        lines, seen, failed = wd.execute(d, Boom(), dry_run=True, stamp="T")
        self.assertTrue(any(line.startswith("T plan:") for line in lines))
        self.assertEqual(failed, 0)

    def test_409_on_an_issue_patch_is_a_warning_not_a_crash_and_is_retried_next_tick(self):
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error_code="boom1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="boom2")]
        issues = [issue("t1", assigneeAgentId="a-eng", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = self.decide(runs, issues=issues)

        class Flaky:
            def send(self, method, path, body=None):
                if path == "/api/issues/t1":
                    raise wd.PaperclipError("409: locked by another run")
                return {}

        lines, seen, failed = wd.execute(d, Flaky(), dry_run=False, stamp="T")
        self.assertGreaterEqual(failed, 1)
        self.assertTrue(any("failed:" in line and "409" in line for line in lines))
        # The issue is still on the lead, so the swap is still recorded and the
        # next tick's decide() retries the same issue.
        self.assertIn("t1", d.swaps["engineering"]["issueIds"])
        retry = self.decide(runs=[], issues=issues, swaps=d.swaps)
        retried = [a for a in retry.actions if a.path == "/api/issues/t1"]
        self.assertEqual(len(retried), 1)
        self.assertEqual(retried[0].body["assigneeAgentId"], "a-standby")


class SwapBackTests(unittest.TestCase):
    """A swap 5 hours old or more swaps back; not before. Swap-back is
    idempotent and multi-tick. It starts (`phase: "returning"`) but is not
    cleared from state until a later tick confirms, from live agent status and
    issue state, that the lead is resumed, the twin is paused, and nothing is
    left on the twin. A failed resume, pause, or issue PATCH just leaves that
    one piece for the next tick to retry. While a run cap still binds the lead,
    swap-back does not start at all."""

    ACTIVE_SWAP = {"engineering": {"twinKey": "engineering-twin", "leadId": "a-eng", "twinId": "a-standby",
                                   "startedAt": "2026-09-26T10:00:00+00:00", "issueIds": ["t1"]}}
    # Before any swap-back action has landed: the lead still paused, the twin
    # still active, exactly as swap-out left them.
    MID_SWAP_AGENTS = [dict(SWAP_AGENTS[0]), dict(SWAP_AGENTS[1], status="paused"),
                       dict(SWAP_AGENTS[2], status="idle")]
    # After a successful swap-back: the lead resumed, the twin paused.
    RETURNED_AGENTS = [dict(SWAP_AGENTS[0]), dict(SWAP_AGENTS[1], status="idle"),
                       dict(SWAP_AGENTS[2], status="paused")]

    def decide(self, issues=(), agents=None, swaps=None, cfg=SWAP_CFG, runs=()):
        agents = agents if agents is not None else list(self.MID_SWAP_AGENTS)
        return wd.decide(cfg, list(runs), list(issues), agents, set(), LABEL, NOW,
                         swaps=dict(swaps) if swaps is not None else dict(self.ACTIVE_SWAP))

    def test_swap_back_starts_but_is_not_cleared_until_live_state_confirms_it(self):
        # NOW is 2026-09-26T15:00:00Z; the swap started at 10:00, exactly 5 hours ago.
        issues = [issue("t1", assigneeAgentId="a-standby", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = self.decide(issues=issues)
        paths = {(a.method, a.path) for a in d.actions}
        self.assertIn(("POST", "/api/agents/a-eng/resume"), paths)
        self.assertIn(("POST", "/api/agents/a-standby/pause"), paths)
        patches = [a for a in d.actions if a.path == "/api/issues/t1"]
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0].body["assigneeAgentId"], "a-eng")
        # Not cleared: nothing yet confirms these actions actually landed.
        self.assertEqual(d.swaps["engineering"]["phase"], "returning")

    def test_confirmed_from_live_state_clears_the_swap(self):
        issues = [issue("t1", assigneeAgentId="a-eng", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        started = dict(self.ACTIVE_SWAP["engineering"], phase="returning")
        d = self.decide(issues=issues, agents=list(self.RETURNED_AGENTS), swaps={"engineering": started})
        self.assertEqual(d.swaps, {})
        self.assertFalse(any(a.path in ("/api/agents/a-eng/resume", "/api/agents/a-standby/pause",
                                        "/api/issues/t1") for a in d.actions))

    def test_a_failed_twin_pause_is_retried_next_tick(self):
        issues = [issue("t1", assigneeAgentId="a-standby", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = self.decide(issues=issues)

        class Flaky:
            def send(self, method, path, body=None):
                if path == "/api/agents/a-standby/pause":
                    raise wd.PaperclipError("500: could not pause")
                return {}

        lines, seen, failed = wd.execute(d, Flaky(), dry_run=False, stamp="T")
        self.assertGreaterEqual(failed, 1)
        # Still recorded, still returning: nothing confirms the twin paused.
        self.assertEqual(d.swaps["engineering"]["phase"], "returning")
        retry = self.decide(issues=issues, swaps=d.swaps)
        self.assertIn(("POST", "/api/agents/a-standby/pause"), [(a.method, a.path) for a in retry.actions])

    def test_a_409_on_the_patch_back_is_a_warning_and_is_retried_next_tick(self):
        issues = [issue("t1", assigneeAgentId="a-standby", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        started = dict(self.ACTIVE_SWAP["engineering"], phase="returning")
        d = self.decide(issues=issues, agents=list(self.RETURNED_AGENTS), swaps={"engineering": started})

        class Flaky:
            def send(self, method, path, body=None):
                if path == "/api/issues/t1":
                    raise wd.PaperclipError("409: locked by another run")
                return {}

        lines, seen, failed = wd.execute(d, Flaky(), dry_run=False, stamp="T")
        self.assertGreaterEqual(failed, 1)
        self.assertTrue(any("failed:" in line and "409" in line for line in lines))
        self.assertEqual(d.swaps["engineering"]["phase"], "returning")
        retry = self.decide(issues=issues, agents=list(self.RETURNED_AGENTS), swaps=d.swaps)
        retried = [a for a in retry.actions if a.path == "/api/issues/t1"]
        self.assertEqual(len(retried), 1)
        self.assertEqual(retried[0].body["assigneeAgentId"], "a-eng")

    def test_not_before_5_hours(self):
        swaps = {"engineering": {**self.ACTIVE_SWAP["engineering"], "startedAt": "2026-09-26T10:00:01+00:00"}}
        d = self.decide(swaps=swaps)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, swaps)

    def test_moved_issue_no_longer_on_the_twin_is_left_alone(self):
        issues = [issue("t1", assigneeAgentId="a-scoper", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = self.decide(issues=issues)
        self.assertFalse(any(a.path == "/api/issues/t1" for a in d.actions))
        self.assertEqual(d.swaps["engineering"]["phase"], "returning")

    def test_lead_not_resumed_if_a_run_cap_still_binds_it(self):
        # While the cap still applies, swap-back does not start at all: no
        # action, the swap stays recorded exactly as it was, and one warning
        # names the lead and the cap.
        cfg = {**SWAP_CFG, "runCaps": {
            "claude_local": {"agents": {"engineering": 1}, "harnessTotal": 999},
            "other_local": {"harnessTotal": 999}, "default": {"harnessTotal": 999}}}
        agents = [dict(SWAP_AGENTS[0]),
                  dict(SWAP_AGENTS[1], status="paused", adapterType="claude_local"),
                  dict(SWAP_AGENTS[2], status="idle", adapterType="other_local")]
        runs = [run("a-eng", "2026-09-26T09:00:00Z", "succeeded")]
        d = self.decide(agents=agents, cfg=cfg, runs=runs)
        self.assertEqual(d.actions, [])
        self.assertEqual(d.swaps, dict(self.ACTIVE_SWAP))
        self.assertTrue(any("engineering" in w and "capped" in w for w in d.warnings))

    def test_swap_back_proceeds_once_the_cap_clears(self):
        cfg = {**SWAP_CFG, "runCaps": {
            "claude_local": {"agents": {"engineering": 5}, "harnessTotal": 999},
            "other_local": {"harnessTotal": 999}, "default": {"harnessTotal": 999}}}
        agents = [dict(SWAP_AGENTS[0]),
                  dict(SWAP_AGENTS[1], status="paused", adapterType="claude_local"),
                  dict(SWAP_AGENTS[2], status="idle", adapterType="other_local")]
        d = self.decide(agents=agents, cfg=cfg)
        self.assertIn(("POST", "/api/agents/a-eng/resume"), [(a.method, a.path) for a in d.actions])
        self.assertEqual(d.swaps["engineering"]["phase"], "returning")

    def test_bad_started_at_clears_the_swap_with_a_warning(self):
        swaps = {"engineering": {**self.ACTIVE_SWAP["engineering"], "startedAt": "not-a-date"}}
        d = self.decide(swaps=swaps)
        self.assertEqual(d.swaps, {})
        self.assertTrue(any("engineering" in w for w in d.warnings))


class ErrorCodeSanitizationTests(unittest.TestCase):
    """A swap comment names only a sanitized `errorCode`, never a run's
    free-text `error`, which is untrusted adapter output that other agents
    read."""

    def test_error_code_is_lowercased_and_reduced_to_safe_characters(self):
        self.assertEqual(wd._run_failure_code({"errorCode": "Acpx_Turn-FAILED!!"}), "acpx_turn_failed")

    def test_long_error_code_is_capped_at_64_characters(self):
        self.assertEqual(wd._run_failure_code({"errorCode": "a" * 100}), "a" * 64)

    def test_free_text_error_is_never_used_even_when_hostile(self):
        hostile = "<script>steal()</script>; DROP TABLE issues; -- $(rm -rf /)"
        code = wd._run_failure_code({"error": hostile, "id": "run-1"})
        self.assertNotIn("<script>", code)
        self.assertNotIn("DROP TABLE", code)
        self.assertEqual(code, "no error code (run run-1)")

    def test_missing_error_code_falls_back_to_naming_the_run(self):
        self.assertEqual(wd._run_failure_code({"id": "r9"}), "no error code (run r9)")
        self.assertEqual(wd._run_failure_code({}), "no error code (run unknown)")

    def test_a_blank_error_code_also_falls_back(self):
        self.assertEqual(wd._run_failure_code({"errorCode": "   ", "id": "r9"}), "no error code (run r9)")

    def test_the_swap_comment_never_carries_the_hostile_error_text(self):
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error="<script>bad</script>", run_id="r1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error="another; DROP TABLE x", run_id="r2")]
        issues = [issue("t1", assigneeAgentId="a-eng", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = wd.decide(SWAP_CFG, runs, issues, SWAP_AGENTS, set(), LABEL, NOW)
        [patch] = [a for a in d.actions if a.path == "/api/issues/t1"]
        self.assertNotIn("<script>", patch.body["comment"])
        self.assertNotIn("DROP TABLE", patch.body["comment"])
        self.assertIn("no error code (run r1)", patch.body["comment"])
        self.assertIn("no error code (run r2)", patch.body["comment"])


TAMPER_SWAP = {"engineering": {"twinKey": "engineering-twin", "leadId": "a-eng", "twinId": "a-standby",
                               "startedAt": "2026-09-26T14:00:00+00:00", "issueIds": []}}


class SwapStateValidationTests(unittest.TestCase):
    """A persisted swap entry is untrusted. It is dropped, with a warning, the
    moment it no longer matches this tick's configured twin pairs or live agent
    ids."""

    def test_a_lead_key_no_longer_a_configured_twin_pair_is_dropped(self):
        cfg = {**SWAP_CFG, "agents": [a for a in SWAP_CFG["agents"] if not a.get("twinOf")]}
        d = wd.decide(cfg, [], [], SWAP_AGENTS, set(), LABEL, NOW, swaps=dict(TAMPER_SWAP))
        self.assertEqual(d.swaps, {})
        self.assertTrue(any("engineering" in w for w in d.warnings))

    def test_a_swap_naming_the_wrong_twin_key_is_dropped(self):
        tampered = {"engineering": {**TAMPER_SWAP["engineering"], "twinKey": "some-other-twin"}}
        d = wd.decide(SWAP_CFG, [], [], SWAP_AGENTS, set(), LABEL, NOW, swaps=tampered)
        self.assertEqual(d.swaps, {})
        self.assertTrue(any("engineering" in w for w in d.warnings))

    def test_a_lead_id_that_does_not_match_the_live_agent_is_dropped(self):
        tampered = {"engineering": {**TAMPER_SWAP["engineering"], "leadId": "a-someone-else"}}
        d = wd.decide(SWAP_CFG, [], [], SWAP_AGENTS, set(), LABEL, NOW, swaps=tampered)
        self.assertEqual(d.swaps, {})
        self.assertTrue(any("engineering" in w for w in d.warnings))

    def test_a_twin_id_that_does_not_match_the_live_agent_is_dropped(self):
        tampered = {"engineering": {**TAMPER_SWAP["engineering"], "twinId": "a-someone-else"}}
        d = wd.decide(SWAP_CFG, [], [], SWAP_AGENTS, set(), LABEL, NOW, swaps=tampered)
        self.assertEqual(d.swaps, {})
        self.assertTrue(any("engineering" in w for w in d.warnings))

    def test_a_matching_entry_survives(self):
        d = wd.decide(SWAP_CFG, [], [], SWAP_AGENTS, set(), LABEL, NOW, swaps=dict(TAMPER_SWAP))
        self.assertIn("engineering", d.swaps)


class SwapOutSkipsDueLeadsTests(unittest.TestCase):
    """On the tick a swap becomes due for swap-back, `_swap_out`'s retry branch
    is skipped for that lead entirely, so no straggler issue is moved onto the
    twin in the same pass that is moving everything off it."""

    def test_no_issue_is_moved_to_the_twin_once_the_swap_is_due(self):
        swaps = {"engineering": {"twinKey": "engineering-twin", "leadId": "a-eng", "twinId": "a-standby",
                                 "startedAt": "2026-09-26T10:00:00+00:00", "issueIds": ["t1"]}}
        # A straggler still on the lead, as if an earlier swap-out PATCH failed.
        issues = [issue("t1", assigneeAgentId="a-eng", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = wd.decide(SWAP_CFG, [], issues, SWAP_AGENTS, set(), LABEL, NOW, swaps=dict(swaps))
        self.assertFalse(any(a.path == "/api/issues/t1" and a.body.get("assigneeAgentId") == "a-standby"
                             for a in d.actions))

    def test_due_keys_include_a_swap_already_marked_returning_regardless_of_age(self):
        swaps = {"engineering": {"twinKey": "engineering-twin", "leadId": "a-eng", "twinId": "a-standby",
                                 "startedAt": NOW.isoformat(), "issueIds": ["t1"], "phase": "returning"}}
        self.assertEqual(wd._due_swap_keys(swaps, NOW), {"engineering"})

    def test_not_yet_due_and_not_returning_is_not_in_due_keys(self):
        swaps = {"engineering": {"twinKey": "engineering-twin", "leadId": "a-eng", "twinId": "a-standby",
                                 "startedAt": NOW.isoformat(), "issueIds": []}}
        self.assertEqual(wd._due_swap_keys(swaps, NOW), set())


class NoModelCallTests(unittest.TestCase):
    """The watchdog calls no model. It reads the Paperclip API and nothing
    else, so it can never be the thing that spends a run."""

    def test_the_script_imports_no_model_client(self):
        text = (SCRIPTS / "paperclip-watchdog.py").read_text().lower()
        for banned in ("import anthropic", "import openai", "completions", "/v1/messages"):
            self.assertNotIn(banned, text, banned)

    def test_every_path_it_writes_to_is_a_paperclip_api_path(self):
        runs = [run("a-eng", "2026-09-26T14:40:00Z", "failed", error_code="b1"),
                run("a-eng", "2026-09-26T14:50:00Z", "failed", error_code="b2")]
        issues = [issue("i1", assigneeAgentId="a-scoper", status="todo"),
                  issue("t1", assigneeAgentId="a-eng", status="in_progress",
                        createdByUserId="local-board", createdByAgentId=None)]
        d = wd.decide(SWAP_CFG, runs, issues, SWAP_AGENTS, set(), LABEL, NOW)
        self.assertTrue(d.actions)
        for action in d.actions:
            self.assertTrue(action.path.startswith("/api/"), action.path)


class HelpTests(unittest.TestCase):
    def test_help_exits_zero_and_names_the_dry_run(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            wd.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--dry-run", out.getvalue())


if __name__ == "__main__":
    unittest.main()
