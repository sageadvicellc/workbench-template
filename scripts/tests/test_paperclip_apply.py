"""Tests for scripts/paperclip-apply.py.

Run with:

    uv run --with pytest --python 3.12 python -m pytest scripts

No test calls a live Paperclip server. FakeClient answers GET requests from a
dictionary and records every write, so the suite is fast and offline.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("paperclip_apply", SCRIPTS / "paperclip-apply.py")
pa = importlib.util.module_from_spec(_spec)
sys.modules["paperclip_apply"] = pa
_spec.loader.exec_module(pa)

CID = "company-1"
EMERY = "agent-emery"


class FakeClient:
    def __init__(self, gets):
        self.gets = gets
        self.writes = []

    def get(self, path):
        if path not in self.gets:
            raise AssertionError(f"unexpected GET {path}")
        return self.gets[path]

    def send(self, method, path, body=None):
        self.writes.append((method, path, body))
        return {"id": "new-agent"}


def make_repo(tmp, agents):
    root = Path(tmp)
    (root / "paperclip").mkdir()
    (root / "paperclip" / "wake-prompt.md").write_text("WAKE {{agent.id}}\n")
    for a in agents:
        p = root / a["instructionsFile"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {a['name']}\n")
    cfg = {
        "companyId": CID,
        "apiBase": "http://127.0.0.1:3100",
        "company": {"requireBoardApprovalForNewAgents": True},
        "experimental": {"enableTaskWatchdogs": False},
        "labels": [{"name": "scope-creep", "color": "#b45309"}],
        "defaults": {
            "adapterConfig": {},
            "adapters": {
                "claude_local": {"model": "claude-sonnet-5", "dangerouslySkipPermissions": False},
                "hermes_local": {"model": "hermes-model"},
            },
            "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
            "permissions": {"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False},
            "wakePromptFile": "paperclip/wake-prompt.md",
        },
        "agents": agents,
    }
    (root / "paperclip" / "company.json").write_text(json.dumps(cfg))
    return root, cfg


EMERY_CFG = {
    "key": "emery", "id": EMERY, "name": "Emery", "role": "ceo", "title": "Chief of staff",
    "instructionsFile": "paperclip/agents/emery/AGENTS.md",
    "adapterConfig": {"maxTurnsPerRun": 60}, "runsPerDay": 8,
}
RESEARCH_CFG = {
    "key": "research", "id": None, "name": "Research lead", "role": "researcher", "title": "Research lead",
    "instructionsFile": "paperclip/agents/research/AGENTS.md",
    "adapterConfig": {"maxTurnsPerRun": 150}, "runsPerDay": 4,
}


def live_emery(**over):
    agent = {
        "id": EMERY, "name": "Emery", "role": "ceo", "title": None, "status": "idle",
        "adapterType": "claude_local",
        "adapterConfig": {"maxTurnsPerRun": 1000, "dangerouslySkipPermissions": True,
                          "instructionsFilePath": "/x/AGENTS.md"},
        "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 20}, "modelProfiles": {}},
        "permissions": {"canCreateAgents": True, "canCreateSkills": True},
    }
    agent.update(over)
    return agent


def base_gets(agents, company=None, experimental=None, labels=None, files=None):
    gets = {
        f"/api/companies/{CID}": company or {"requireBoardApprovalForNewAgents": False},
        "/api/instance/settings/experimental": experimental or {"enableTaskWatchdogs": False},
        f"/api/companies/{CID}/labels": labels if labels is not None else [],
        f"/api/companies/{CID}/agents": agents,
    }
    for agent_id, content in (files or {}).items():
        gets[f"/api/agents/{agent_id}/instructions-bundle/file?path=AGENTS.md"] = {"content": content}
    return gets


class PlanTests(unittest.TestCase):
    def plan(self, agents_cfg, gets):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, agents_cfg)
            client = FakeClient(gets)
            return pa.plan_actions(cfg, client, root)

    def test_company_flag_is_patched_when_it_differs(self):
        actions = self.plan([], base_gets([]))
        company = [a for a in actions if a.path == f"/api/companies/{CID}"]
        self.assertEqual(len(company), 1)
        self.assertEqual(company[0].body, {"requireBoardApprovalForNewAgents": True})

    def test_nothing_is_planned_when_live_state_matches(self):
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"id": "l1", "name": "scope-creep"}])
        self.assertEqual(self.plan([], gets), [])

    def test_missing_label_is_created(self):
        actions = self.plan([], base_gets([], company={"requireBoardApprovalForNewAgents": True}))
        self.assertEqual([(a.method, a.path) for a in actions],
                         [("POST", f"/api/companies/{CID}/labels")])

    def test_existing_agent_gets_adapter_runtime_permissions_and_instructions(self):
        gets = base_gets([live_emery()], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={EMERY: "old onboarding text"})
        actions = self.plan([EMERY_CFG], gets)
        by_path = {(a.method, a.path): a for a in actions}

        patch = by_path[("PATCH", f"/api/agents/{EMERY}")].body
        self.assertEqual(patch["adapterConfig"]["maxTurnsPerRun"], 60)
        self.assertFalse(patch["adapterConfig"]["dangerouslySkipPermissions"])
        self.assertEqual(patch["adapterConfig"]["promptTemplate"], "WAKE {{agent.id}}\n")
        self.assertNotIn("instructionsFilePath", patch["adapterConfig"])
        self.assertEqual(patch["runtimeConfig"]["heartbeat"]["maxConcurrentRuns"], 1)
        self.assertIn("modelProfiles", patch["runtimeConfig"])
        self.assertEqual(patch["title"], "Chief of staff")

        perms = by_path[("PATCH", f"/api/agents/{EMERY}/permissions")].body
        self.assertEqual(perms, {"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False})

        put = by_path[("PUT", f"/api/agents/{EMERY}/instructions-bundle/file")].body
        self.assertEqual(put, {"path": "AGENTS.md", "content": "# Emery\n"})

    def test_matching_agent_plans_no_writes(self):
        live = live_emery(
            title="Chief of staff",
            adapterConfig={"maxTurnsPerRun": 60, "model": "claude-sonnet-5",
                           "dangerouslySkipPermissions": False, "promptTemplate": "WAKE {{agent.id}}\n"},
            runtimeConfig={"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
            permissions={"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False},
        )
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={EMERY: "# Emery\n"})
        self.assertEqual(self.plan([EMERY_CFG], gets), [])

    def test_missing_agent_is_created_with_bundle(self):
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}])
        actions = self.plan([RESEARCH_CFG], gets)
        self.assertEqual(len(actions), 1)
        body = actions[0].body
        self.assertEqual((actions[0].method, actions[0].path), ("POST", f"/api/companies/{CID}/agents"))
        self.assertEqual(body["name"], "Research lead")
        self.assertEqual(body["role"], "researcher")
        self.assertEqual(body["instructionsBundle"],
                         {"entryFile": "AGENTS.md", "files": {"AGENTS.md": "# Research lead\n"}})
        self.assertEqual(body["permissions"]["canAssignTasks"], False)
        self.assertEqual(body["adapterConfig"]["promptTemplate"], "WAKE {{agent.id}}\n")

    def test_agent_without_id_is_matched_by_name(self):
        live = live_emery(id="agent-r", name="Research lead", role="researcher")
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={"agent-r": "# Research lead\n"})
        actions = self.plan([RESEARCH_CFG], gets)
        self.assertTrue(all(a.method != "POST" for a in actions))
        self.assertIn(("PATCH", "/api/agents/agent-r"), [(a.method, a.path) for a in actions])


class PortabilityTests(unittest.TestCase):
    def test_switching_runtime_replaces_config_and_keeps_instructions(self):
        hermes = dict(EMERY_CFG, adapterType="hermes_local")
        gets = base_gets([live_emery()], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={EMERY: "# Emery\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [hermes])
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{EMERY}")
        self.assertEqual(patch["adapterType"], "hermes_local")
        self.assertTrue(patch["replaceAdapterConfig"])
        self.assertEqual(patch["adapterConfig"]["model"], "hermes-model")
        self.assertEqual(patch["adapterConfig"]["instructionsFilePath"], "/x/AGENTS.md")
        self.assertNotIn("dangerouslySkipPermissions", patch["adapterConfig"])

    def test_new_agent_uses_its_own_adapter_profile(self):
        hermes = dict(RESEARCH_CFG, adapterType="hermes_local")
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}])
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [hermes])
            body = pa.plan_actions(cfg, FakeClient(gets), root)[0].body
        self.assertEqual(body["adapterType"], "hermes_local")
        self.assertEqual(body["adapterConfig"]["model"], "hermes-model")


class LibTests(unittest.TestCase):
    def test_duplicate_live_names_raise(self):
        live = [live_emery(id="x1", name="Research lead"), live_emery(id="x2", name="Research lead")]
        with self.assertRaises(pa.PaperclipError):
            pa.agent_ids({"agents": [RESEARCH_CFG]}, live)

    def test_token_refused_over_plain_http_to_remote_host(self):
        with self.assertRaises(pa.PaperclipError):
            pa.Client("http://example.com:3100", token="secret")
        pa.Client("http://127.0.0.1:3100", token="secret")
        pa.Client("https://example.com", token="secret")


class ApplyTests(unittest.TestCase):
    def test_dry_run_sends_nothing(self):
        client = FakeClient({})
        actions = [pa.Action("PATCH", "/x", {"a": 1}, "change x")]
        out = pa.run_actions(actions, client, apply=False)
        self.assertEqual(client.writes, [])
        self.assertIn("change x", out[0])

    def test_partial_failure_reports_how_many_landed(self):
        class Flaky(FakeClient):
            def send(self, method, path, body=None):
                if path == "/y":
                    raise pa.PaperclipError("boom")
                return super().send(method, path, body)

        client = Flaky({})
        actions = [pa.Action("PATCH", "/x", {}, "x"), pa.Action("POST", "/y", {}, "y")]
        echoed = []
        with self.assertRaises(pa.PaperclipError) as ctx:
            pa.run_actions(actions, client, apply=True, echo=echoed.append)
        self.assertIn("1 of 2", str(ctx.exception))
        self.assertEqual(echoed, ["done: x"])

    def test_apply_sends_each_action_in_order(self):
        client = FakeClient({})
        actions = [pa.Action("PATCH", "/x", {"a": 1}, "x"), pa.Action("POST", "/y", {"b": 2}, "y")]
        pa.run_actions(actions, client, apply=True)
        self.assertEqual(client.writes, [("PATCH", "/x", {"a": 1}), ("POST", "/y", {"b": 2})])


if __name__ == "__main__":
    unittest.main()
