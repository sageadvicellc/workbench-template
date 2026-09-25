"""Tests for scripts/paperclip-watchdog.py.

Run with:

    uv run --with pytest --python 3.12 python -m pytest scripts

Every test feeds synthetic runs and issues to the pure decision function, so
nothing here calls a live Paperclip server.
"""

import importlib.util
import sys
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
        {"key": "emery", "id": "a-emery", "name": "Emery", "runsPerDay": 2},
        {"key": "research", "id": None, "name": "Research lead", "runsPerDay": 1},
    ],
    "watchdog": {"authFailureBurst": 3, "authFailurePattern": "OAuth session expired"},
}

AGENTS = [
    {"id": "a-emery", "name": "Emery", "status": "idle"},
    {"id": "a-research", "name": "Research lead", "status": "idle"},
]


def run(agent, at, status="succeeded", error=None):
    return {"agentId": agent, "createdAt": at, "status": status, "error": error}


def issue(id_, **over):
    base = {
        "id": id_, "identifier": id_.upper(), "status": "todo", "createdByUserId": None,
        "createdByAgentId": "a-emery", "originKind": "manual", "assigneeAgentId": None,
        "assigneeUserId": None, "labelIds": [],
    }
    base.update(over)
    return base


def decide(runs=(), issues=(), agents=AGENTS, seen=()):
    return wd.decide(CFG, list(runs), list(issues), list(agents), set(seen), LABEL, NOW)


class RunCapTests(unittest.TestCase):
    def test_agent_at_cap_today_is_paused(self):
        d = decide(runs=[run("a-emery", "2026-09-26T01:00:00Z"), run("a-emery", "2026-09-26T09:00:00Z")])
        self.assertEqual([(a.method, a.path) for a in d.actions], [("POST", "/api/agents/a-emery/pause")])

    def test_runs_from_yesterday_do_not_count(self):
        d = decide(runs=[run("a-emery", "2026-09-25T23:59:00Z"), run("a-emery", "2026-09-26T09:00:00Z")])
        self.assertEqual(d.actions, [])

    def test_agent_without_config_id_is_matched_by_name(self):
        d = decide(runs=[run("a-research", "2026-09-26T09:00:00Z")])
        self.assertEqual([a.path for a in d.actions], ["/api/agents/a-research/pause"])

    def test_paused_agent_is_not_paused_again(self):
        agents = [dict(AGENTS[0], status="paused"), AGENTS[1]]
        d = decide(runs=[run("a-emery", "2026-09-26T01:00:00Z")] * 3, agents=agents)
        self.assertEqual(d.actions, [])


class AuthBurstTests(unittest.TestCase):
    def test_burst_of_auth_failures_pauses_every_agent_once(self):
        err = "Internal error: Failed to authenticate: OAuth session expired and could not be refreshed"
        runs = [run("a-emery", "2026-09-26T14:50:00Z", "failed", err)] * 3
        d = decide(runs=runs)
        paths = sorted(a.path for a in d.actions)
        self.assertEqual(paths, ["/api/agents/a-emery/pause", "/api/agents/a-research/pause"])

    def test_old_auth_failures_are_ignored(self):
        err = "OAuth session expired"
        runs = [run("a-emery", "2026-09-25T20:00:00Z", "failed", err)] * 3
        self.assertEqual(decide(runs=runs).actions, [])


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

    def test_person_created_issue_is_never_touched(self):
        d = decide(issues=[issue("i4", createdByUserId="local-board", createdByAgentId=None,
                                 assigneeAgentId="a-emery")])
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
                                 assigneeAgentId="a-emery")])
        self.assertEqual(d.actions[0].body["status"], "backlog")


class RobustnessTests(unittest.TestCase):
    def test_bad_timestamp_counts_toward_the_cap(self):
        runs = [run("a-emery", "2026-09-26T01:00:00Z"), {"agentId": "a-emery", "createdAt": "not a date"}]
        d = decide(runs=runs)
        self.assertEqual([a.path for a in d.actions], ["/api/agents/a-emery/pause"])

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
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            wd._save_seen(path, {"b", "a"})
            self.assertEqual(wd._load_seen(path), ({"a", "b"}, None))
            path.write_text("{truncated")
            seen, warning = wd._load_seen(path)
            self.assertEqual(seen, set())
            self.assertIn("unreadable", warning)


class ParseTests(unittest.TestCase):
    def test_parse_accepts_z_and_offset(self):
        self.assertEqual(wd.parse_ts("2026-09-26T01:00:00.123Z").tzinfo, timezone.utc)
        self.assertEqual(wd.parse_ts("2026-09-26T01:00:00+00:00").hour, 1)


if __name__ == "__main__":
    unittest.main()
