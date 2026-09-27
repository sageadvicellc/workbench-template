"""Tests for scripts/paperclip-apply.py.

Run with:

    uv run --quiet --with pytest python -m pytest scripts/tests -q

No test calls a live Paperclip server. FakeClient answers GET requests from a
dictionary and records every write, so the suite is fast and offline. Every
name here is invented for the test: no agent, company, or person in this file
belongs to any practice.
"""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("paperclip_apply", SCRIPTS / "paperclip-apply.py")
pa = importlib.util.module_from_spec(_spec)
sys.modules["paperclip_apply"] = pa
_spec.loader.exec_module(pa)

CID = "company-1"
SCOPER = "agent-scoper"


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
                "other_local": {"model": "other-model"},
            },
            "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
            "permissions": {"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False},
            "wakePromptFile": "paperclip/wake-prompt.md",
        },
        "agents": agents,
    }
    (root / "paperclip" / "company.json").write_text(json.dumps(cfg))
    return root, cfg


SCOPER_CFG = {
    "key": "scoper", "id": SCOPER, "name": "Scoper", "role": "ceo", "title": "Chief of staff",
    "instructionsFile": "paperclip/agents/scoper/AGENTS.md",
    "adapterConfig": {"maxTurnsPerRun": 60}, "runsPerDay": 8,
}
RESEARCH_CFG = {
    "key": "research", "id": None, "name": "Research lead", "role": "researcher", "title": "Research lead",
    "instructionsFile": "paperclip/agents/research/AGENTS.md",
    "adapterConfig": {"maxTurnsPerRun": 150}, "runsPerDay": 4,
}


def live_scoper(**over):
    agent = {
        "id": SCOPER, "name": "Scoper", "role": "ceo", "title": None, "status": "idle",
        "adapterType": "claude_local",
        "adapterConfig": {"maxTurnsPerRun": 1000, "dangerouslySkipPermissions": True,
                          "instructionsFilePath": "/x/AGENTS.md"},
        "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 20}, "modelProfiles": {}},
        "permissions": {"canCreateAgents": True, "canCreateSkills": True},
    }
    agent.update(over)
    return agent


def matching_live_scoper(**over):
    """`live_scoper()`, adjusted so the base plan (name, adapter, permissions,
    instructions) already matches `SCOPER_CFG`. A test that starts here and
    overrides one field isolates that field's diff from the rest."""
    base = {
        "title": "Chief of staff",
        "adapterConfig": {"maxTurnsPerRun": 60, "model": "claude-sonnet-5",
                          "dangerouslySkipPermissions": False, "promptTemplate": "WAKE {{agent.id}}\n"},
        "runtimeConfig": {"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
        "permissions": {"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False},
    }
    base.update(over)
    return live_scoper(**base)


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

    def test_an_in_sync_apply_sends_nothing_and_says_so(self):
        """The apply compares before it writes. An in-sync tree is a no-op even
        with `--apply`, which is what makes a rerun safe."""
        gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        actions = self.plan([SCOPER_CFG], gets)
        self.assertEqual(actions, [])
        client = FakeClient({})
        pa.run_actions(actions, client, apply=True)
        self.assertEqual(client.writes, [])
        self.assertEqual(pa._summary_line(actions, applied=True), "in sync: nothing to change")

    def test_nested_company_setting_compares_by_value(self):
        want = {"interactionResolverGovernance": {"request_confirmation": {"defaultPolicy": "human_only",
                                                                          "cap": "human_only"}}}
        live = {"interactionResolverGovernance": {"request_confirmation": {"cap": "human_only",
                                                                          "defaultPolicy": "human_only"}}}
        self.assertEqual(pa._diff(want, live), {})
        self.assertEqual(pa._diff(want, {"interactionResolverGovernance": {}}), want)

    def test_missing_label_is_created(self):
        actions = self.plan([], base_gets([], company={"requireBoardApprovalForNewAgents": True}))
        self.assertEqual([(a.method, a.path) for a in actions],
                         [("POST", f"/api/companies/{CID}/labels")])

    def test_existing_agent_gets_adapter_runtime_permissions_and_instructions(self):
        gets = base_gets([live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "old onboarding text"})
        actions = self.plan([SCOPER_CFG], gets)
        by_path = {(a.method, a.path): a for a in actions}

        patch = by_path[("PATCH", f"/api/agents/{SCOPER}")].body
        self.assertEqual(patch["adapterConfig"]["maxTurnsPerRun"], 60)
        self.assertFalse(patch["adapterConfig"]["dangerouslySkipPermissions"])
        self.assertEqual(patch["adapterConfig"]["promptTemplate"], "WAKE {{agent.id}}\n")
        self.assertNotIn("instructionsFilePath", patch["adapterConfig"])
        self.assertEqual(patch["runtimeConfig"]["heartbeat"]["maxConcurrentRuns"], 1)
        self.assertIn("modelProfiles", patch["runtimeConfig"])
        self.assertEqual(patch["title"], "Chief of staff")

        perms = by_path[("PATCH", f"/api/agents/{SCOPER}/permissions")].body
        self.assertEqual(perms, {"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False})

        put = by_path[("PUT", f"/api/agents/{SCOPER}/instructions-bundle/file")].body
        self.assertEqual(put, {"path": "AGENTS.md", "content": "# Scoper\n"})

    def test_the_heartbeat_ships_off(self):
        """A heartbeat timer turns an idle agent into an unbounded loop, so the
        default is `enabled: false`. This proves the plan carries that."""
        gets = base_gets([live_scoper(runtimeConfig={"heartbeat": {"enabled": True, "maxConcurrentRuns": 1}})],
                         company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        actions = self.plan([SCOPER_CFG], gets)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{SCOPER}")
        self.assertIs(patch["runtimeConfig"]["heartbeat"]["enabled"], False)

    def test_echoed_model_profile_gets_the_adapter_config_the_server_requires(self):
        live = live_scoper(runtimeConfig={"heartbeat": {"enabled": True},
                                         "modelProfiles": {"cheap": {"enabled": False}}})
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        actions = self.plan([SCOPER_CFG], gets)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{SCOPER}")
        self.assertEqual(patch["runtimeConfig"]["modelProfiles"],
                         {"cheap": {"adapterConfig": {}, "enabled": False}})

    def test_matching_agent_plans_no_writes(self):
        live = live_scoper(
            title="Chief of staff",
            adapterConfig={"maxTurnsPerRun": 60, "model": "claude-sonnet-5",
                           "dangerouslySkipPermissions": False, "promptTemplate": "WAKE {{agent.id}}\n"},
            runtimeConfig={"heartbeat": {"enabled": False, "maxConcurrentRuns": 1}},
            permissions={"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False},
        )
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        self.assertEqual(self.plan([SCOPER_CFG], gets), [])

    def test_missing_agent_is_created_with_bundle(self):
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}])
        actions = self.plan([RESEARCH_CFG], gets)
        self.assertEqual(len(actions), 1)
        body = actions[0].body
        self.assertEqual((actions[0].method, actions[0].path), ("POST", f"/api/companies/{CID}/agent-hires"))
        self.assertEqual(body["name"], "Research lead")
        self.assertEqual(body["role"], "researcher")
        self.assertEqual(body["instructionsBundle"],
                         {"entryFile": "AGENTS.md", "files": {"AGENTS.md": "# Research lead\n"}})
        self.assertEqual(body["permissions"]["canAssignTasks"], False)
        self.assertNotIn("promptTemplate", body["adapterConfig"])

    def test_agent_max_concurrent_runs_overrides_the_default(self):
        live = matching_live_scoper()
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        actions = self.plan([dict(SCOPER_CFG, maxConcurrentRuns=3)], gets)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{SCOPER}")
        self.assertEqual(patch["runtimeConfig"]["heartbeat"], {"enabled": False, "maxConcurrentRuns": 3})

    def test_matching_max_concurrent_runs_plans_nothing(self):
        live = matching_live_scoper(runtimeConfig={"heartbeat": {"enabled": False, "maxConcurrentRuns": 3}})
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        self.assertEqual(self.plan([dict(SCOPER_CFG, maxConcurrentRuns=3)], gets), [])

    def test_hire_takes_its_own_max_concurrent_runs(self):
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}])
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [dict(RESEARCH_CFG, maxConcurrentRuns=2)])
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
            self.assertEqual(actions[0].body["runtimeConfig"]["heartbeat"]["maxConcurrentRuns"], 2)
            self.assertEqual(cfg["defaults"]["runtimeConfig"]["heartbeat"]["maxConcurrentRuns"], 1)

    def test_agent_without_id_is_matched_by_name(self):
        live = live_scoper(id="agent-r", name="Research lead", role="researcher")
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={"agent-r": "# Research lead\n"})
        actions = self.plan([RESEARCH_CFG], gets)
        self.assertTrue(all(a.method != "POST" for a in actions))
        self.assertIn(("PATCH", "/api/agents/agent-r"), [(a.method, a.path) for a in actions])


class OrgChartTests(unittest.TestCase):
    def test_reports_to_is_patched_when_it_differs(self):
        agent_cfg = dict(SCOPER_CFG, reportsTo="research")
        gets = base_gets([matching_live_scoper(reportsTo=None),
                          matching_live_scoper(id="agent-r", name="Research lead", title="Research lead",
                                               reportsTo=None)],
                         company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}],
                         files={SCOPER: "# Scoper\n", "agent-r": "# Research lead\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [agent_cfg, dict(RESEARCH_CFG, id="agent-r")])
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{SCOPER}")
        self.assertEqual(patch["reportsTo"], "agent-r")

    def test_matching_reports_to_plans_nothing(self):
        agent_cfg = dict(SCOPER_CFG, reportsTo=None)
        gets = base_gets([matching_live_scoper(reportsTo=None)], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [agent_cfg])
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        self.assertEqual(actions, [])


class AssignmentPolicyTests(unittest.TestCase):
    def plan(self, agent_cfg, live, apply_flag):
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [agent_cfg])
            cfg["applyAssignmentPolicy"] = apply_flag
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_off_by_default_plans_nothing_for_protection_or_grants(self):
        agent_cfg = dict(SCOPER_CFG, protected=True, assignScopeGrant={"agentIds": ["scoper"]})
        actions = self.plan(agent_cfg, matching_live_scoper(), apply_flag=False)
        self.assertEqual(actions, [])

    def test_enabled_sets_protected_mode_when_missing(self):
        agent_cfg = dict(SCOPER_CFG, protected=True)
        actions = self.plan(agent_cfg, matching_live_scoper(), apply_flag=True)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{SCOPER}/permissions")
        self.assertEqual(patch["authorizationPolicy"], {"assignmentPolicy": {"mode": "protected"}})

    def test_already_protected_plans_no_permissions_change(self):
        agent_cfg = dict(SCOPER_CFG, protected=True)
        live = matching_live_scoper(permissions={"canCreateAgents": False, "canCreateSkills": False,
                                                "canAssignTasks": False,
                                                "authorizationPolicy": {"assignmentPolicy": {"mode": "protected"}}})
        actions = self.plan(agent_cfg, live, apply_flag=True)
        self.assertFalse(any(a.path == f"/api/agents/{SCOPER}/permissions" for a in actions))

    def test_grant_scope_resolves_agent_keys_to_live_ids(self):
        agent_cfg = dict(SCOPER_CFG, assignScopeGrant={"agentIds": ["scoper"]})
        live = matching_live_scoper(access={"membership": {"id": "member-1"}, "grants": []})
        actions = self.plan(agent_cfg, live, apply_flag=True)
        patch = next(a.body for a in actions if a.path == f"/api/companies/{CID}/members/member-1/role-and-grants")
        self.assertEqual(patch["grants"], [{"permissionKey": "tasks:assign_scope", "scope": {"agentIds": [SCOPER]}}])

    def test_matching_grant_plans_nothing(self):
        agent_cfg = dict(SCOPER_CFG, assignScopeGrant={"agentIds": ["scoper"]})
        live = matching_live_scoper(
            access={"membership": {"id": "member-1"},
                    "grants": [{"permissionKey": "tasks:assign_scope", "scope": {"agentIds": [SCOPER]}}]})
        actions = self.plan(agent_cfg, live, apply_flag=True)
        self.assertFalse(any("role-and-grants" in a.path for a in actions))

    def test_grant_update_preserves_the_member_s_other_grants(self):
        agent_cfg = dict(SCOPER_CFG, assignScopeGrant={"agentIds": ["scoper"]})
        live = matching_live_scoper(access={
            "membership": {"id": "member-1", "status": "active"},
            "grants": [{"permissionKey": "tools:connect", "scope": None}],
        })
        actions = self.plan(agent_cfg, live, apply_flag=True)
        patch = next(a.body for a in actions if a.path == f"/api/companies/{CID}/members/member-1/role-and-grants")
        self.assertIn({"permissionKey": "tools:connect", "scope": None}, patch["grants"])
        self.assertIn({"permissionKey": "tasks:assign_scope", "scope": {"agentIds": [SCOPER]}}, patch["grants"])
        self.assertEqual(patch["status"], "active")


PIPELINE_SPEC = {"name": "build", "stages": [
    {"key": "scope", "name": "Scope", "kind": "open", "position": 0,
     "config": {"automation": {"assigneeAgent": "scoper"}}},
    {"key": "done", "name": "Done", "kind": "done", "position": 1, "config": {}},
]}


class PipelineTests(unittest.TestCase):
    """One stage at a time gets a 422 the moment an earlier stage's
    `approveToStageKey`/`rejectToStageKey` names a stage that does not exist
    yet ("references an unknown stage"). Every stage must go in the one
    pipeline-create call instead."""

    def plan(self, live_pipelines, apply_flag, agents=(SCOPER_CFG,), live_agents=None, spec=None):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, list(agents))
            (root / "paperclip" / "pipelines").mkdir()
            (root / "paperclip" / "pipelines" / "build.json").write_text(json.dumps(spec or PIPELINE_SPEC))
            cfg["pipelines"] = [{"key": "build", "file": "paperclip/pipelines/build.json"}]
            cfg["applyPipelines"] = apply_flag
            gets = base_gets(live_agents if live_agents is not None else [matching_live_scoper()],
                             company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}],
                             files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/pipelines"] = live_pipelines
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_off_by_default_plans_nothing(self):
        self.assertEqual(self.plan([], apply_flag=False), [])

    def test_missing_pipeline_is_created_with_every_stage_in_one_call(self):
        actions = self.plan([], apply_flag=True)
        create = next(a for a in actions if a.path == f"/api/companies/{CID}/pipelines")
        self.assertEqual(create.body["key"], "build")
        self.assertEqual(create.body["name"], "build")
        self.assertEqual([s["key"] for s in create.body["stages"]], ["scope", "done"])
        scope_stage = next(s for s in create.body["stages"] if s["key"] == "scope")
        # The server strips config.automation from the create call, so it must
        # never be sent there.
        self.assertNotIn("automation", scope_stage["config"])

    def test_an_automated_stage_gets_a_later_patch_ref_d_to_its_own_key(self):
        actions = self.plan([], apply_flag=True)
        create = next(a for a in actions if a.path == f"/api/companies/{CID}/pipelines")
        patches = [a for a in actions if a.path == "__pipeline_stage_automation__"]
        self.assertEqual(len(patches), 1)  # only "scope" carries automation; "done" does not
        patch = patches[0]
        self.assertEqual(patch.method, "PATCH")
        self.assertEqual(patch.body, {"config": {"automation": {"assigneeAgentId": SCOPER}}})
        self.assertEqual(patch.ref, f"{create.ref}:stage:scope")

    def test_existing_pipeline_by_name_plans_nothing_when_stages_and_automation_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG])
            (root / "paperclip" / "pipelines").mkdir()
            (root / "paperclip" / "pipelines" / "build.json").write_text(json.dumps(PIPELINE_SPEC))
            cfg["pipelines"] = [{"key": "build", "file": "paperclip/pipelines/build.json"}]
            cfg["applyPipelines"] = True
            gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/pipelines"] = [{"id": "pipe-1", "name": "build"}]
            gets["/api/pipelines/pipe-1"] = {"stages": [
                {"key": "scope", "config": {"onEnter": {"type": "run_routine", "routineId": "r1"}}},
                {"key": "done", "config": {}},
            ]}
            gets[f"/api/companies/{CID}/routines"] = [{"id": "r1", "assigneeAgentId": SCOPER}]
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        self.assertEqual(actions, [])

    def test_stage_with_unresolved_assignee_agent_raises(self):
        with self.assertRaises(pa.PaperclipError):
            self.plan([], apply_flag=True, agents=(), live_agents=[])

    def test_create_response_with_no_id_raises_before_any_stage_patch(self):
        class NoIdClient(FakeClient):
            def send(self, method, path, body=None):
                self.writes.append((method, path, body))
                return {} if path.endswith("/pipelines") else super().send(method, path, body)

        actions = self.plan([], apply_flag=True)
        client = NoIdClient({})
        with self.assertRaises(pa.PaperclipError) as ctx:
            pa.run_actions(actions, client, apply=True)
        self.assertIn("returned no id", str(ctx.exception))
        self.assertEqual(len(client.writes), 1)

    def test_create_response_missing_a_stage_raises_a_clear_error_naming_it(self):
        class MissingStageClient(FakeClient):
            def send(self, method, path, body=None):
                self.writes.append((method, path, body))
                if path.endswith("/pipelines"):
                    return {"id": "pipe-1", "stages": [{"key": "done", "id": "stage-done"}]}
                return {}

        actions = self.plan([], apply_flag=True)
        with self.assertRaises(pa.PaperclipError) as ctx:
            pa.run_actions(actions, MissingStageClient({}), apply=True)
        self.assertIn("scope", str(ctx.exception))

    def test_run_actions_sends_the_patch_to_the_stage_id_from_the_create_response(self):
        class SeqClient(FakeClient):
            def send(self, method, path, body=None):
                self.writes.append((method, path, body))
                if path.endswith("/pipelines"):
                    return {"id": "pipe-1", "stages": [
                        {"key": "scope", "id": "stage-scope"},
                        {"key": "done", "id": "stage-done"},
                    ]}
                return {}

        actions = self.plan([], apply_flag=True)
        client = SeqClient({})
        pa.run_actions(actions, client, apply=True)
        self.assertEqual(client.writes[-1],
                         ("PATCH", "/api/pipelines/pipe-1/stages/stage-scope",
                          {"config": {"automation": {"assigneeAgentId": SCOPER}}}))


class PipelineAutomationPatchTests(unittest.TestCase):
    """The server strips config.automation from the create call; only a PATCH to
    the created stage's own id sets it, and that PATCH carries the stage's full
    stripped config, not automation alone, since whether the server merges or
    replaces `config` is unverified."""

    def _plan(self, spec, agents=(SCOPER_CFG,)):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, list(agents))
            (root / "paperclip" / "pipelines").mkdir()
            (root / "paperclip" / "pipelines" / "build.json").write_text(json.dumps(spec))
            cfg["pipelines"] = [{"key": "build", "file": "paperclip/pipelines/build.json"}]
            cfg["applyPipelines"] = True
            gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/pipelines"] = []
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_automation_extras_survive_into_the_patch(self):
        spec = {"name": "build", "stages": [
            {"key": "scope", "name": "Scope", "kind": "open", "position": 0,
             "config": {"automation": {"assigneeAgent": "scoper", "titleTemplate": "Scope the case",
                                       "instructionsBody": "Read the case, then transition it."}}},
            {"key": "done", "name": "Done", "kind": "done", "position": 1, "config": {}},
        ]}
        actions = self._plan(spec)
        create = next(a for a in actions if a.path.endswith("/pipelines"))
        scope_stage = next(s for s in create.body["stages"] if s["key"] == "scope")
        self.assertNotIn("automation", scope_stage["config"])
        patch = next(a for a in actions if a.path == "__pipeline_stage_automation__")
        self.assertEqual(patch.body, {"config": {"automation": {
            "assigneeAgentId": SCOPER,
            "titleTemplate": "Scope the case",
            "instructionsBody": "Read the case, then transition it.",
        }}})

    def test_a_stage_with_no_automation_gets_no_patch_action(self):
        spec = {"name": "build", "stages": [
            {"key": "done", "name": "Done", "kind": "done", "position": 0, "config": {}},
        ]}
        actions = self._plan(spec)
        self.assertFalse(any(a.path == "__pipeline_stage_automation__" for a in actions))

    def test_the_patch_carries_the_stage_s_full_config_not_only_automation(self):
        spec = {"name": "build", "stages": [
            {"key": "scope", "name": "Scope", "kind": "open", "position": 0,
             "config": {"someFlag": True, "automation": {"assigneeAgent": "scoper"}}},
            {"key": "done", "name": "Done", "kind": "done", "position": 1, "config": {}},
        ]}
        actions = self._plan(spec)
        patch = next(a for a in actions if a.path == "__pipeline_stage_automation__")
        self.assertEqual(patch.body, {"config": {"someFlag": True, "automation": {"assigneeAgentId": SCOPER}}})


class PipelineDriftTests(unittest.TestCase):
    """A pipeline that exists by name is not necessarily built right, or built
    at all past its first stage. A rerun must never call that "in sync":
    compare live stage content (not just presence) against the file and print
    drift instead of silently doing nothing.

    A wired stage's config reads `{"onEnter": {"type": "run_routine",
    "routineId": "<uuid>"}, "approver": {...}}`. The routine's assignee is
    `assigneeAgentId` on `GET /api/companies/{cid}/routines`, matched by
    `routineId`.
    """

    def _plan(self, live_detail, spec=None, live_routines=None):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG])
            (root / "paperclip" / "pipelines").mkdir()
            (root / "paperclip" / "pipelines" / "build.json").write_text(json.dumps(spec or PIPELINE_SPEC))
            cfg["pipelines"] = [{"key": "build", "file": "paperclip/pipelines/build.json"}]
            cfg["applyPipelines"] = True
            gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/pipelines"] = [{"id": "pipe-1", "name": "build"}]
            gets["/api/pipelines/pipe-1"] = live_detail
            if live_routines is not None:
                gets[f"/api/companies/{CID}/routines"] = live_routines
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_fully_synced_pipeline_plans_nothing(self):
        actions = self._plan(
            {"stages": [
                {"key": "scope", "config": {"onEnter": {"type": "run_routine", "routineId": "r1"}}},
                {"key": "done", "config": {}},
            ]},
            live_routines=[{"id": "r1", "title": "Scope the case", "assigneeAgentId": SCOPER}],
        )
        self.assertEqual(actions, [])

    def test_missing_stage_is_reported_as_drift_not_silence(self):
        actions = self._plan(
            {"stages": [{"key": "scope", "config": {"onEnter": {"type": "run_routine", "routineId": "r1"}}}]},
            live_routines=[{"id": "r1", "assigneeAgentId": SCOPER}],
        )
        self.assertEqual(len(actions), 1)
        note = actions[0]
        self.assertEqual(note.method, "NOTE")
        self.assertIn("build", note.summary)
        self.assertIn("done", note.summary)

    def test_unwired_automation_is_reported_as_drift(self):
        actions = self._plan({"stages": [
            {"key": "scope", "config": {}},
            {"key": "done", "config": {}},
        ]})
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].method, "NOTE")
        self.assertIn("scope", actions[0].summary)
        self.assertIn("no automation wired", actions[0].summary)

    def test_automation_wired_to_the_wrong_agent_is_reported_as_drift(self):
        actions = self._plan(
            {"stages": [
                {"key": "scope", "config": {"onEnter": {"type": "run_routine", "routineId": "r1"}}},
                {"key": "done", "config": {}},
            ]},
            live_routines=[{"id": "r1", "assigneeAgentId": "agent-someone-else"}],
        )
        self.assertEqual(len(actions), 1)
        note = actions[0]
        self.assertIn("scope", note.summary)
        self.assertIn(SCOPER, note.summary)
        self.assertIn("agent-someone-else", note.summary)

    def test_old_type_userid_derived_approver_is_reported_as_drift(self):
        # A stage created before the {type, userId} fix was silently read by the
        # server as {"kind": "any_human"}. A rerun today must catch that drift
        # on an already-created pipeline, not only prevent it on a new one.
        spec = {"name": "build", "stages": [
            {"key": "approve", "name": "Approve", "kind": "review", "position": 0,
             "config": {"requireApproval": True, "approver": {"kind": "user", "id": "local-board"},
                        "approveToStageKey": "done", "rejectToStageKey": "approve"}},
            {"key": "done", "name": "Done", "kind": "done", "position": 1, "config": {}},
        ]}
        actions = self._plan({"stages": [
            {"key": "approve", "config": {"approver": {"kind": "any_human"}, "requireApproval": True,
                                          "approveToStageKey": "done", "rejectToStageKey": "approve"}},
            {"key": "done", "config": {}},
        ]}, spec=spec)
        self.assertEqual(len(actions), 1)
        note = actions[0]
        self.assertIn("approver", note.summary)
        self.assertIn("any_human", note.summary)
        self.assertIn("local-board", note.summary)

    def test_a_mismatched_approve_to_stage_key_is_reported_as_drift(self):
        spec = {"name": "build", "stages": [
            {"key": "approve", "name": "Approve", "kind": "review", "position": 0,
             "config": {"approver": {"kind": "user", "id": "local-board"}, "approveToStageKey": "build"}},
            {"key": "done", "name": "Done", "kind": "done", "position": 1, "config": {}},
        ]}
        actions = self._plan({"stages": [
            {"key": "approve", "config": {"approver": {"kind": "user", "id": "local-board"},
                                          "approveToStageKey": "done"}},
            {"key": "done", "config": {}},
        ]}, spec=spec)
        self.assertEqual(len(actions), 1)
        note = actions[0]
        self.assertIn("approveToStageKey", note.summary)
        self.assertIn("build", note.summary)
        self.assertIn("done", note.summary)

    def test_drift_is_never_a_destructive_write(self):
        actions = self._plan({"stages": [{"key": "scope", "config": {}}]})
        self.assertTrue(actions)
        self.assertTrue(all(a.method == "NOTE" for a in actions))

    def test_a_drift_note_prints_and_sends_nothing(self):
        actions = self._plan(
            {"stages": [
                {"key": "scope", "config": {"onEnter": {"type": "run_routine", "routineId": "r1"}}},
                {"key": "done", "config": {}},
            ]},
            live_routines=[{"id": "r1", "assigneeAgentId": "someone-else"}],
        )
        client = FakeClient({})
        echoed = []
        lines = pa.run_actions(actions, client, apply=True, echo=echoed.append)
        self.assertEqual(client.writes, [])
        self.assertTrue(any(line.startswith("drift:") for line in lines))
        self.assertEqual(lines, echoed)


class FreshCompanyBootstrapTests(unittest.TestCase):
    """A brand-new company has no live agents. Hiring a manager and its report
    in the same run must not fail resolving `reportsTo` before the manager
    exists, and pipeline planning (which needs live agent ids for
    `assigneeAgent`) must wait for a pass where every agent already exists."""

    def test_a_new_agent_reporting_to_another_new_agent_hires_without_reports_to(self):
        manager = dict(SCOPER_CFG, id=None, reportsTo=None)
        report = dict(RESEARCH_CFG, reportsTo="scoper")
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}])
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [manager, report])
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        hires = {a.body["name"]: a for a in actions if a.path.endswith("/agent-hires")}
        self.assertEqual(len(hires), 2)
        self.assertIsNone(hires["Research lead"].body["reportsTo"])

    def test_a_second_pass_after_both_hires_land_patches_reports_to(self):
        """main() reruns `plan_actions` once every hire from the first pass has
        landed. This drives `plan_actions` the same way, twice: once against no
        live agents (both hires, `reportsTo` deferred), then again against both
        agents now live by name (as a real `--apply` leaves them, since neither
        cfg entry here carries an id), and checks that the second call is the
        one that PATCHes `reportsTo` in."""
        manager = dict(SCOPER_CFG, id=None, reportsTo=None)
        report = dict(RESEARCH_CFG, reportsTo="scoper")
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [manager, report])

            gets_first = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                                   labels=[{"name": "scope-creep"}])
            first_actions = pa.plan_actions(cfg, FakeClient(gets_first), root)
            self.assertEqual(len(first_actions), 2)
            self.assertTrue(all(a.path.endswith("/agent-hires") for a in first_actions))

            research_live_id = "agent-research"
            live_agents = [
                matching_live_scoper(reportsTo=None),
                live_scoper(id=research_live_id, name="Research lead", role="researcher",
                            title="Research lead", reportsTo=None),
            ]
            gets_second = base_gets(live_agents, company={"requireBoardApprovalForNewAgents": True},
                                    labels=[{"name": "scope-creep"}],
                                    files={SCOPER: "# Scoper\n", research_live_id: "# Research lead\n"})
            second_actions = pa.plan_actions(cfg, FakeClient(gets_second), root)
        patch = next(a for a in second_actions if a.path == f"/api/agents/{research_live_id}")
        self.assertEqual(patch.body["reportsTo"], SCOPER)

    def test_reports_to_naming_an_unconfigured_key_still_raises(self):
        report = dict(RESEARCH_CFG, reportsTo="no-such-key")
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}])
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [report])
            with self.assertRaises(pa.PaperclipError):
                pa.plan_actions(cfg, FakeClient(gets), root)

    def test_a_new_agent_reporting_to_an_already_live_manager_resolves_immediately(self):
        report = dict(RESEARCH_CFG, reportsTo="scoper")
        gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG, report])
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        hire = next(a for a in actions if a.path.endswith("/agent-hires"))
        self.assertEqual(hire.body["reportsTo"], SCOPER)

    def test_pipeline_planning_is_deferred_while_any_agent_is_still_being_hired(self):
        manager = dict(SCOPER_CFG, id=None, reportsTo=None)
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}])
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [manager])
            (root / "paperclip" / "pipelines").mkdir()
            (root / "paperclip" / "pipelines" / "build.json").write_text(json.dumps(PIPELINE_SPEC))
            cfg["pipelines"] = [{"key": "build", "file": "paperclip/pipelines/build.json"}]
            cfg["applyPipelines"] = True
            gets[f"/api/companies/{CID}/pipelines"] = []
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        self.assertFalse(any(a.path.endswith("/pipelines") or a.path.startswith("__pipeline") for a in actions))
        self.assertTrue(any(a.path.endswith("/agent-hires") for a in actions))

    def test_pipeline_planning_resumes_once_every_agent_already_exists(self):
        gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG])
            (root / "paperclip" / "pipelines").mkdir()
            (root / "paperclip" / "pipelines" / "build.json").write_text(json.dumps(PIPELINE_SPEC))
            cfg["pipelines"] = [{"key": "build", "file": "paperclip/pipelines/build.json"}]
            cfg["applyPipelines"] = True
            gets[f"/api/companies/{CID}/pipelines"] = []
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        self.assertTrue(any(a.path.endswith("/pipelines") for a in actions))


class SummaryLineTests(unittest.TestCase):
    """The dry-run/apply closing line must never say "in sync" when a drift
    note is in the plan."""

    def test_no_actions_is_in_sync(self):
        self.assertEqual(pa._summary_line([], applied=False), "in sync: nothing to change")

    def test_a_lone_drift_note_is_not_in_sync_and_has_no_count_line(self):
        note = pa.Action("NOTE", "__drift__", None, "pipeline build: drift")
        self.assertIsNone(pa._summary_line([note], applied=False))

    def test_a_real_change_reports_its_count_on_a_dry_run(self):
        change = pa.Action("PATCH", "/x", {}, "x")
        self.assertEqual(pa._summary_line([change], applied=False),
                         "1 change(s) planned. Run again with --apply to send them.")

    def test_a_real_change_plus_a_drift_note_counts_only_the_change(self):
        change = pa.Action("PATCH", "/x", {}, "x")
        note = pa.Action("NOTE", "__drift__", None, "pipeline build: drift")
        self.assertEqual(pa._summary_line([change, note], applied=False),
                         "1 change(s) planned. Run again with --apply to send them.")

    def test_an_applied_run_prints_no_extra_count_line(self):
        change = pa.Action("PATCH", "/x", {}, "x")
        self.assertIsNone(pa._summary_line([change], applied=True))


class ApproverValidationTests(unittest.TestCase):
    def _plan_with_stage(self, stage_config, agents=(SCOPER_CFG,)):
        spec = {"name": "build", "stages": [
            {"key": "approve", "name": "Approve", "kind": "review", "position": 0, "config": stage_config},
            {"key": "done", "name": "Done", "kind": "done", "position": 1, "config": {}},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, list(agents))
            (root / "paperclip" / "pipelines").mkdir()
            (root / "paperclip" / "pipelines" / "build.json").write_text(json.dumps(spec))
            cfg["pipelines"] = [{"key": "build", "file": "paperclip/pipelines/build.json"}]
            cfg["applyPipelines"] = True
            gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/pipelines"] = []
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_old_type_user_id_shape_raises_a_clear_error(self):
        with self.assertRaises(pa.PaperclipError) as ctx:
            self._plan_with_stage({"requireApproval": True, "approver": {"type": "user", "userId": "local-board"}})
        self.assertIn("approve", str(ctx.exception))
        self.assertIn("kind", str(ctx.exception))

    def test_kind_id_shape_plans_without_raising(self):
        actions = self._plan_with_stage({"requireApproval": True, "approver": {"kind": "user", "id": "local-board"}})
        self.assertTrue(actions)

    def test_user_kind_with_no_id_raises(self):
        with self.assertRaises(pa.PaperclipError):
            self._plan_with_stage({"requireApproval": True, "approver": {"kind": "user"}})

    def test_any_human_kind_needs_no_id(self):
        actions = self._plan_with_stage({"requireApproval": True, "approver": {"kind": "any_human"}})
        self.assertTrue(actions)

    def test_an_unknown_approver_kind_raises(self):
        with self.assertRaises(pa.PaperclipError):
            self._plan_with_stage({"approver": {"kind": "committee", "id": "x"}})

    def test_a_stage_with_no_approver_is_unaffected(self):
        actions = self._plan_with_stage({"automation": {"assigneeAgent": "scoper"}})
        self.assertTrue(actions)


class RoutineTests(unittest.TestCase):
    def test_missing_routine_is_created_with_its_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG])
            (root / "paperclip" / "routines").mkdir()
            (root / "paperclip" / "routines" / "cap-audit.md").write_text("read this, write that\n")
            cfg["routines"] = [{"key": "cap-audit", "file": "paperclip/routines/cap-audit.md",
                                "assigneeAgent": "scoper", "name": "cap-audit"}]
            gets = base_gets([live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/routines"] = []
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        routine = next(a for a in actions if a.path == f"/api/companies/{CID}/routines")
        self.assertEqual(routine.body["title"], "cap-audit")
        self.assertEqual(routine.body["description"], "read this, write that\n")
        self.assertEqual(routine.body["assigneeAgentId"], SCOPER)

    def test_existing_routine_by_title_plans_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [])
            (root / "paperclip" / "routines").mkdir()
            (root / "paperclip" / "routines" / "cap-audit.md").write_text("x\n")
            cfg["routines"] = [{"key": "cap-audit", "file": "paperclip/routines/cap-audit.md",
                                "assigneeAgent": "scoper", "name": "cap-audit"}]
            gets = base_gets([], company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}])
            gets[f"/api/companies/{CID}/routines"] = [{"title": "cap-audit"}]
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        self.assertEqual(actions, [])

    SCHEDULED = {"key": "roadmap-sync", "file": "paperclip/routines/roadmap-sync.md",
                 "assigneeAgent": "scoper", "name": "roadmap-sync",
                 "concurrencyPolicy": "skip_if_active", "catchUpPolicy": "skip_missed",
                 "schedule": {"cronExpression": "0 9 * * 1", "timezone": "America/New_York"}}

    def _plan_scheduled(self, live_routines, agents=()):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, list(agents))
            (root / "paperclip" / "routines").mkdir()
            (root / "paperclip" / "routines" / "roadmap-sync.md").write_text("pull, compare\n")
            cfg["routines"] = [dict(self.SCHEDULED)]
            live = [live_scoper()] if agents else []
            gets = base_gets(live, company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/routines"] = live_routines
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_new_routine_carries_its_policies_and_waits_for_its_trigger(self):
        actions = self._plan_scheduled([], agents=[SCOPER_CFG])
        routine = next(a for a in actions if a.path == f"/api/companies/{CID}/routines")
        self.assertEqual(routine.body["concurrencyPolicy"], "skip_if_active")
        self.assertEqual(routine.body["catchUpPolicy"], "skip_missed")
        # The routine has no id yet; the second pass adds the trigger.
        self.assertFalse([a for a in actions if a.path.endswith("/triggers")])

    def test_existing_routine_without_its_schedule_gets_a_trigger(self):
        actions = self._plan_scheduled([{"id": "r9", "title": "roadmap-sync", "triggers": []}])
        self.assertEqual(len(actions), 1)
        self.assertEqual((actions[0].method, actions[0].path), ("POST", "/api/routines/r9/triggers"))
        self.assertEqual(actions[0].body, {"kind": "schedule", "cronExpression": "0 9 * * 1",
                                           "timezone": "America/New_York", "enabled": True})

    def test_routine_for_an_agent_hired_this_pass_waits_for_the_second_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG])
            (root / "paperclip" / "routines").mkdir()
            (root / "paperclip" / "routines" / "roadmap-sync.md").write_text("x\n")
            cfg["routines"] = [dict(self.SCHEDULED)]
            gets = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}])
            gets[f"/api/companies/{CID}/routines"] = []
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        self.assertTrue(any("hire" in a.path or "agent" in a.path for a in actions))
        self.assertFalse([a for a in actions if "routines" in a.path])

    def test_live_assignee_routine_is_planned_while_another_hire_is_pending(self):
        knowledge = dict(SCOPER_CFG, key="knowledge-office", name="Knowledge office", id=None)
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG, knowledge])
            (root / "paperclip" / "routines").mkdir()
            for name in ("cap-audit", "roadmap-sync"):
                (root / "paperclip" / "routines" / f"{name}.md").write_text("x\n")
            cfg["routines"] = [
                {"key": "cap-audit", "file": "paperclip/routines/cap-audit.md",
                 "assigneeAgent": "scoper", "name": "cap-audit"},
                dict(self.SCHEDULED, assigneeAgent="knowledge-office"),
            ]
            gets = base_gets([live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
            gets[f"/api/companies/{CID}/routines"] = []
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        created = [a.body["title"] for a in actions if a.path == f"/api/companies/{CID}/routines"]
        self.assertEqual(created, ["cap-audit"])

    def test_existing_routine_with_its_schedule_plans_nothing(self):
        live = [{"id": "r9", "title": "roadmap-sync", "triggers": [
            {"kind": "schedule", "cronExpression": "0 9 * * 1", "timezone": "America/New_York"}]}]
        self.assertEqual(self._plan_scheduled(live), [])


class PortabilityTests(unittest.TestCase):
    def test_switching_runtime_replaces_config_and_keeps_instructions(self):
        other = dict(SCOPER_CFG, adapterType="other_local")
        gets = base_gets([live_scoper()], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [other])
            actions = pa.plan_actions(cfg, FakeClient(gets), root)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{SCOPER}")
        self.assertEqual(patch["adapterType"], "other_local")
        self.assertTrue(patch["replaceAdapterConfig"])
        self.assertEqual(patch["adapterConfig"]["model"], "other-model")
        self.assertEqual(patch["adapterConfig"]["instructionsFilePath"], "/x/AGENTS.md")
        self.assertNotIn("dangerouslySkipPermissions", patch["adapterConfig"])

    def test_new_agent_uses_its_own_adapter_profile(self):
        other = dict(RESEARCH_CFG, adapterType="other_local")
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True}, labels=[{"name": "scope-creep"}])
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [other])
            body = pa.plan_actions(cfg, FakeClient(gets), root)[0].body
        self.assertEqual(body["adapterType"], "other_local")
        self.assertEqual(body["adapterConfig"]["model"], "other-model")


class PausedAgentTests(unittest.TestCase):
    """An agent whose config carries `"status": "paused"`, such as a standby
    twin, is hired active (the hire API takes no starting status) and paused
    right after."""

    PAUSED = dict(SCOPER_CFG, status="paused")

    def plan(self, live, files=None):
        gets = base_gets([live] if live else [], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files=files or {})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [self.PAUSED])
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_an_active_agent_wanting_paused_is_paused(self):
        actions = self.plan(matching_live_scoper(status="idle"), files={SCOPER: "# Scoper\n"})
        self.assertEqual([(a.method, a.path) for a in actions],
                         [("POST", f"/api/agents/{SCOPER}/pause")])

    def test_an_already_paused_agent_plans_no_pause(self):
        actions = self.plan(matching_live_scoper(status="paused"), files={SCOPER: "# Scoper\n"})
        self.assertEqual(actions, [])


class LibTests(unittest.TestCase):
    def test_duplicate_live_names_raise(self):
        live = [live_scoper(id="x1", name="Research lead"), live_scoper(id="x2", name="Research lead")]
        with self.assertRaises(pa.PaperclipError):
            pa.agent_ids({"agents": [RESEARCH_CFG]}, live)

    def test_token_refused_over_plain_http_to_remote_host(self):
        with self.assertRaises(pa.PaperclipError):
            pa.Client("http://example.com:3100", token="secret")
        pa.Client("http://127.0.0.1:3100", token="secret")
        pa.Client("https://example.com", token="secret")

    def test_unresolved_agent_key_in_reports_to_raises(self):
        agent_cfg = dict(SCOPER_CFG, reportsTo="no-such-key")
        gets = base_gets([matching_live_scoper(reportsTo=None)], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [agent_cfg])
            with self.assertRaises(pa.PaperclipError):
                pa.plan_actions(cfg, FakeClient(gets), root)

    def test_unresolved_agent_key_in_grant_scope_raises(self):
        agent_cfg = dict(SCOPER_CFG, assignScopeGrant={"agentIds": ["no-such-key"]})
        live = matching_live_scoper(access={"membership": {"id": "member-1"}, "grants": []})
        gets = base_gets([live], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files={SCOPER: "# Scoper\n"})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [agent_cfg])
            cfg["applyAssignmentPolicy"] = True
            with self.assertRaises(pa.PaperclipError):
                pa.plan_actions(cfg, FakeClient(gets), root)


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

    def test_hire_is_approved_in_the_same_step(self):
        class Hiring(FakeClient):
            def send(self, method, path, body=None):
                super().send(method, path, body)
                if path.endswith("/agent-hires"):
                    return {"agent": {"id": "a-new"}, "approval": {"id": "ap-1"}}
                return {}

        client = Hiring({})
        lines = pa.run_actions([pa.Action("POST", "/api/companies/c/agent-hires", {"name": "R"}, "hire R")],
                               client, apply=True)
        self.assertEqual([w[1] for w in client.writes],
                         ["/api/companies/c/agent-hires", "/api/approvals/ap-1/approve"])
        self.assertIn("a-new", lines[0])

    def test_a_hire_that_needs_no_approval_is_not_approved(self):
        """With `requireBoardApprovalForNewAgents` off, the hire route returns
        no approval and nothing is approved."""
        class Hiring(FakeClient):
            def send(self, method, path, body=None):
                super().send(method, path, body)
                return {"agent": {"id": "a-new"}}

        client = Hiring({})
        pa.run_actions([pa.Action("POST", "/api/companies/c/agent-hires", {"name": "R"}, "hire R")],
                       client, apply=True)
        self.assertEqual([w[1] for w in client.writes], ["/api/companies/c/agent-hires"])

    def test_failed_approval_says_the_hire_landed(self):
        class HalfHire(FakeClient):
            def send(self, method, path, body=None):
                if path.endswith("/approve"):
                    raise pa.PaperclipError("503")
                return {"agent": {"id": "a-new"}, "approval": {"id": "ap-1"}}

        with self.assertRaises(pa.PaperclipError) as ctx:
            pa.run_actions([pa.Action("POST", "/api/companies/c/agent-hires", {"name": "R"}, "hire R")],
                           HalfHire({}), apply=True)
        self.assertIn("landed as agent a-new", str(ctx.exception))
        self.assertIn("1 of 1", str(ctx.exception))

    def test_apply_sends_each_action_in_order(self):
        client = FakeClient({})
        actions = [pa.Action("PATCH", "/x", {"a": 1}, "x"), pa.Action("POST", "/y", {"b": 2}, "y")]
        pa.run_actions(actions, client, apply=True)
        self.assertEqual(client.writes, [("PATCH", "/x", {"a": 1}), ("POST", "/y", {"b": 2})])


class BoardApprovedHireTests(unittest.TestCase):
    """End to end, offline: `main --apply` against a company that requires board
    approval hires the agent, approves the hire (running this script with
    `--apply` is the board's approval), and then a second pass sets what the
    hire body could not carry: the wake prompt, which the server refuses on a
    new agent, and the permissions, which a hire is given by default."""

    class Hiring:
        """Answers GETs from a company with no agents, then, once a hire has
        landed, from a company holding that agent as the server leaves it."""

        def __init__(self):
            self.writes = []
            self.hired = None

        def get(self, path):
            if path == f"/api/companies/{CID}":
                return {"requireBoardApprovalForNewAgents": True}
            if path == "/api/instance/settings/experimental":
                return {"enableTaskWatchdogs": False}
            if path == f"/api/companies/{CID}/labels":
                return [{"name": "scope-creep"}]
            if path == f"/api/companies/{CID}/agents":
                return [self.hired] if self.hired else []
            if path.endswith("/instructions-bundle/file?path=AGENTS.md"):
                return {"content": "# Research lead\n"}
            raise AssertionError(f"unexpected GET {path}")

        def send(self, method, path, body=None):
            self.writes.append((method, path, body))
            if path.endswith("/agent-hires"):
                # As the server leaves a hire: no promptTemplate, and a default
                # task-assign grant the config does not ask for.
                self.hired = {
                    "id": "a-new", "name": body["name"], "role": body["role"], "title": body["title"],
                    "status": "idle", "adapterType": body["adapterType"], "reportsTo": None,
                    "adapterConfig": dict(body["adapterConfig"]),
                    "runtimeConfig": body["runtimeConfig"],
                    "permissions": {**body["permissions"], "canAssignTasks": True},
                }
                return {"agent": {"id": "a-new"}, "approval": {"id": "ap-1"}}
            return {}

    def test_hire_then_approval_then_a_second_pass_sets_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [RESEARCH_CFG])
            config_path = root / "paperclip" / "company.json"
            client = self.Hiring()
            with mock.patch.object(pa, "Client", lambda *a, **k: client), \
                    mock.patch.object(pa, "REPO_ROOT", root), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                code = pa.main(["--config", str(config_path), "--apply"])
        self.assertEqual(code, 0)
        paths = [(m, p) for m, p, _ in client.writes]
        self.assertEqual(paths[0], ("POST", f"/api/companies/{CID}/agent-hires"))
        self.assertEqual(paths[1], ("POST", "/api/approvals/ap-1/approve"))
        self.assertIn(("PATCH", "/api/agents/a-new"), paths)
        self.assertIn(("PATCH", "/api/agents/a-new/permissions"), paths)
        prompt_patch = next(b for _, p, b in client.writes if p == "/api/agents/a-new")
        self.assertEqual(prompt_patch["adapterConfig"]["promptTemplate"], "WAKE {{agent.id}}\n")
        perms = next(b for _, p, b in client.writes if p == "/api/agents/a-new/permissions")
        self.assertIs(perms["canAssignTasks"], False)
        self.assertIn("second pass", out.getvalue())


class RerunAfterPartialFailureTests(unittest.TestCase):
    """A run that fails part way leaves the changes that landed in place. The
    rerun plans only what is still different, which is what makes the apply
    safe to run again rather than something to undo by hand."""

    def test_the_rerun_plans_only_the_unlanded_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [SCOPER_CFG])
            # Before: the company flag and the label are both wrong.
            gets = base_gets([matching_live_scoper()], company={"requireBoardApprovalForNewAgents": False},
                             labels=[], files={SCOPER: "# Scoper\n"})
            first = pa.plan_actions(cfg, FakeClient(gets), root)
            self.assertEqual([a.method for a in first], ["PATCH", "POST"])

            class FlakyLabel(FakeClient):
                def send(self, method, path, body=None):
                    if path.endswith("/labels"):
                        raise pa.PaperclipError("500")
                    return super().send(method, path, body)

            with self.assertRaises(pa.PaperclipError) as ctx:
                pa.run_actions(first, FlakyLabel({}), apply=True)
            self.assertIn("1 of 2", str(ctx.exception))

            # After: the company flag landed, the label did not.
            gets_again = base_gets([matching_live_scoper()],
                                   company={"requireBoardApprovalForNewAgents": True},
                                   labels=[], files={SCOPER: "# Scoper\n"})
            second = pa.plan_actions(cfg, FakeClient(gets_again), root)
        self.assertEqual([(a.method, a.path) for a in second],
                         [("POST", f"/api/companies/{CID}/labels")])


class PerAgentPermissionTests(unittest.TestCase):
    """An agent's own `permissions` block overrides `defaults.permissions`."""

    DEFAULT_PERMS = {"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False}
    LEAD_PERMS = {"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": True}

    def plan(self, agents_cfg, live_agents, files=None, apply_flag=False):
        gets = base_gets(live_agents, company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}], files=files or {})
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, agents_cfg)
            cfg["applyAssignmentPolicy"] = apply_flag
            return pa.plan_actions(cfg, FakeClient(gets), root)

    def test_desired_permissions_merge_agent_over_defaults(self):
        cfg = {"defaults": {"permissions": dict(self.DEFAULT_PERMS)}}
        self.assertEqual(pa._desired_permissions(cfg, {"permissions": {"canAssignTasks": True}}), self.LEAD_PERMS)
        self.assertEqual(pa._desired_permissions(cfg, {}), self.DEFAULT_PERMS)

    def test_desired_permissions_do_not_mutate_defaults(self):
        cfg = {"defaults": {"permissions": dict(self.DEFAULT_PERMS)}}
        pa._desired_permissions(cfg, {"permissions": {"canAssignTasks": True}})
        self.assertEqual(cfg["defaults"]["permissions"], self.DEFAULT_PERMS)

    def test_new_lead_is_hired_with_its_own_permissions(self):
        lead = dict(RESEARCH_CFG, permissions={"canAssignTasks": True})
        actions = self.plan([lead], [])
        self.assertEqual(actions[0].body["permissions"], self.LEAD_PERMS)

    def test_new_worker_is_hired_with_default_permissions(self):
        actions = self.plan([RESEARCH_CFG], [])
        self.assertEqual(actions[0].body["permissions"], self.DEFAULT_PERMS)

    def test_existing_lead_permissions_are_patched_to_its_own_block(self):
        lead = dict(SCOPER_CFG, permissions={"canAssignTasks": True})
        actions = self.plan([lead], [matching_live_scoper()], files={SCOPER: "# Scoper\n"})
        perms = [a.body for a in actions if a.path == f"/api/agents/{SCOPER}/permissions"]
        self.assertEqual(perms, [self.LEAD_PERMS])

    def test_existing_lead_matching_its_own_block_plans_nothing(self):
        lead = dict(SCOPER_CFG, permissions={"canAssignTasks": True})
        live = matching_live_scoper(permissions=dict(self.LEAD_PERMS))
        self.assertEqual(self.plan([lead], [live], files={SCOPER: "# Scoper\n"}), [])

    def test_protected_mode_patch_carries_the_agent_s_own_assign_right(self):
        lead = dict(SCOPER_CFG, protected=True, permissions={"canAssignTasks": True})
        live = matching_live_scoper(permissions=dict(self.LEAD_PERMS))
        actions = self.plan([lead], [live], files={SCOPER: "# Scoper\n"}, apply_flag=True)
        patch = next(a.body for a in actions if a.path == f"/api/agents/{SCOPER}/permissions")
        self.assertTrue(patch["canAssignTasks"])
        self.assertEqual(patch["authorizationPolicy"], {"assignmentPolicy": {"mode": "protected"}})


class MissingInstructionsTests(unittest.TestCase):
    """A missing `instructionsFile` is a config error with a clear message, even
    on a dry run, not a raw FileNotFoundError."""

    def test_missing_file_raises_paperclip_error_naming_key_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = {"key": "writer", "instructionsFile": "paperclip/agents/writer/AGENTS.md"}
            with self.assertRaises(pa.PaperclipError) as ctx:
                pa._instructions(agent, Path(tmp))
            self.assertIn("writer", str(ctx.exception))
            self.assertIn("paperclip/agents/writer/AGENTS.md", str(ctx.exception))

    def test_dry_run_plan_for_a_new_agent_with_no_file_raises_clearly(self):
        gets = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                         labels=[{"name": "scope-creep"}])
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [RESEARCH_CFG])
            (root / RESEARCH_CFG["instructionsFile"]).unlink()
            with self.assertRaises(pa.PaperclipError) as ctx:
                pa.plan_actions(cfg, FakeClient(gets), root)
            self.assertIn("research", str(ctx.exception))

    def test_main_reports_the_missing_file_and_exits_nonzero(self):
        missing = dict(RESEARCH_CFG, instructionsFile="paperclip/agents/no-such-agent/AGENTS.md")
        with tempfile.TemporaryDirectory() as tmp:
            root, cfg = make_repo(tmp, [])
            cfg["agents"] = [missing]
            config_path = root / "paperclip" / "company.json"
            config_path.write_text(json.dumps(cfg))
            gets = base_gets([], company={"requireBoardApprovalForNewAgents": True},
                             labels=[{"name": "scope-creep"}])
            with mock.patch.object(pa, "Client", lambda *a, **k: FakeClient(gets)), \
                    mock.patch.object(pa, "REPO_ROOT", root), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                code = pa.main(["--config", str(config_path)])
            self.assertEqual(code, 1)
            written = err.getvalue()
            self.assertIn("research", written)
            self.assertIn("paperclip/agents/no-such-agent/AGENTS.md", written)


class HelpTests(unittest.TestCase):
    def test_help_exits_zero_and_names_the_apply_flag(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out), self.assertRaises(SystemExit) as caught:
            pa.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--apply", out.getvalue())


if __name__ == "__main__":
    unittest.main()
