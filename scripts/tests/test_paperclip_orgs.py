"""Tests for a second Paperclip company run from the same `paperclip/` tree.

Covers the config overlay in `paperclip_lib.load_config` (`extends` plus
`agentOverrides`), the launchd label prefix loader, goal planning in
`paperclip-apply.py`, the state-file setting in `paperclip-watchdog.py`, and
`paperclip-new-org.py`.

    uv run --quiet --with pytest python -m pytest scripts/tests -q

No test calls a live Paperclip server, touches launchd, or writes outside a
temporary directory. Every company and agent name here is invented for the
test.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import paperclip_lib as lib  # noqa: E402


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pa = _load("paperclip_apply", "paperclip-apply.py")
wd = _load("paperclip_watchdog", "paperclip-watchdog.py")
no = _load("paperclip_new_org", "paperclip-new-org.py")

PREFIX = "org.example.workbench"

BASE = {
    "companyId": "base-co",
    "apiBase": "http://127.0.0.1:3100",
    "company": {"requireBoardApprovalForNewAgents": True},
    "runCaps": {"claude_local": {"agents": {"scoper": 999, "engineering": 999}, "harnessTotal": 999},
                "default": {"harnessTotal": 999}},
    "watchdog": {"logFile": ".paperclip/watchdog.log", "leadKeys": ["engineering"]},
    "prospectiveAgents": [{"key": "writer", "id": "w-1"}],
    "agents": [
        {"key": "scoper", "id": "base-scoper", "name": "Scoper", "runsPerDay": 999,
         "adapterConfig": {"model": "m", "maxTurnsPerRun": 60}},
        {"key": "engineering", "id": "base-eng", "name": "Engineering lead", "runsPerDay": 999},
    ],
}


def write_pair(tmp, overlay, base=None):
    root = Path(tmp)
    (root / "orgs").mkdir()
    (root / "company.json").write_text(json.dumps(base or BASE))
    path = root / "orgs" / "new.json"
    path.write_text(json.dumps(overlay))
    return path


class OverlayTests(unittest.TestCase):
    def test_config_without_extends_loads_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "company.json"
            p.write_text(json.dumps(BASE))
            self.assertEqual(lib.load_config(p), BASE)

    def test_overlay_merges_dicts_and_replaces_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {
                "extends": "../company.json", "companyId": "new-co",
                "company": {"name": "Second company"},
                "runCaps": {"claude_local": {"agents": {"scoper": 250}}},
                "watchdog": {"logFile": ".paperclip/watchdog-new.log"},
                "prospectiveAgents": [],
            })
            cfg = lib.load_config(path)
        self.assertNotIn("extends", cfg)
        self.assertEqual(cfg["companyId"], "new-co")
        self.assertEqual(cfg["company"], {"requireBoardApprovalForNewAgents": True, "name": "Second company"})
        self.assertEqual(cfg["runCaps"]["claude_local"]["agents"], {"scoper": 250, "engineering": 999})
        self.assertEqual(cfg["runCaps"]["claude_local"]["harnessTotal"], 999)
        self.assertEqual(cfg["watchdog"]["leadKeys"], ["engineering"])
        self.assertEqual(cfg["watchdog"]["logFile"], ".paperclip/watchdog-new.log")
        self.assertEqual(cfg["prospectiveAgents"], [])

    def test_another_company_drops_the_base_agent_ids(self):
        # A base id belongs to the base company. Carried over, it could match
        # nothing or, worse, the wrong agent, so the overlay starts from names.
        with tempfile.TemporaryDirectory() as tmp:
            cfg = lib.load_config(write_pair(tmp, {"extends": "../company.json", "companyId": "new-co"}))
        self.assertEqual([a.get("id") for a in cfg["agents"]], [None, None])
        self.assertEqual([a["name"] for a in cfg["agents"]], ["Scoper", "Engineering lead"])

    def test_an_empty_company_id_also_drops_the_base_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = lib.load_config(write_pair(tmp, {"extends": "../company.json", "companyId": None}))
        self.assertTrue(all(a.get("id") is None for a in cfg["agents"]))

    def test_same_company_keeps_the_base_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = lib.load_config(write_pair(tmp, {"extends": "../company.json"}))
        self.assertEqual([a["id"] for a in cfg["agents"]], ["base-scoper", "base-eng"])

    def test_agent_overrides_merge_by_key_and_set_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = lib.load_config(write_pair(tmp, {
                "extends": "../company.json", "companyId": "new-co",
                "agentOverrides": {"scoper": {"id": "new-scoper", "runsPerDay": 250,
                                              "adapterConfig": {"maxTurnsPerRun": 80}}},
            }))
        scoper = cfg["agents"][0]
        self.assertEqual(scoper["id"], "new-scoper")
        self.assertEqual(scoper["runsPerDay"], 250)
        self.assertEqual(scoper["adapterConfig"], {"model": "m", "maxTurnsPerRun": 80})
        self.assertNotIn("agentOverrides", cfg)

    def test_an_override_for_an_unknown_key_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {"extends": "../company.json", "agentOverrides": {"nobody": {"id": "x"}}})
            with self.assertRaises(lib.PaperclipError) as err:
                lib.load_config(path)
        self.assertIn("nobody", str(err.exception))

    def test_loading_twice_gives_the_same_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {"extends": "../company.json", "companyId": "new-co",
                                    "agentOverrides": {"scoper": {"id": "new-scoper"}}})
            self.assertEqual(lib.load_config(path), lib.load_config(path))

    def test_extra_agents_are_appended_after_the_merged_base_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {
                "extends": "../company.json", "companyId": "new-co",
                "extraAgents": [{"key": "engineering-twin", "id": None, "name": "Engineering standby",
                                 "twinOf": "engineering"}],
            })
            cfg = lib.load_config(path)
        self.assertEqual([a["key"] for a in cfg["agents"]], ["scoper", "engineering", "engineering-twin"])
        self.assertEqual(cfg["agents"][-1]["name"], "Engineering standby")

    def test_no_extra_agents_key_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {"extends": "../company.json"})
            cfg = lib.load_config(path)
        self.assertEqual([a["key"] for a in cfg["agents"]], ["scoper", "engineering"])

    def test_an_extra_agent_key_colliding_with_a_base_agent_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {
                "extends": "../company.json",
                "extraAgents": [{"key": "scoper", "id": None, "name": "Ghost"}],
            })
            with self.assertRaises(lib.PaperclipError) as err:
                lib.load_config(path)
        self.assertIn("scoper", str(err.exception))

    def test_duplicate_extra_agent_keys_are_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {
                "extends": "../company.json",
                "extraAgents": [{"key": "x", "id": None, "name": "A"}, {"key": "x", "id": None, "name": "B"}],
            })
            with self.assertRaises(lib.PaperclipError):
                lib.load_config(path)

    def test_extra_agents_loading_twice_gives_the_same_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {
                "extends": "../company.json", "companyId": "new-co",
                "extraAgents": [{"key": "engineering-twin", "id": None, "name": "Engineering standby",
                                 "twinOf": "engineering"}],
            })
            self.assertEqual(lib.load_config(path), lib.load_config(path))


class LaunchdLabelPrefixTests(unittest.TestCase):
    """The reverse-DNS prefix every launchd label here is built from. It is a
    setting, never a literal in a script, because a label prefix names a
    practice. A missing or placeholder value is a clear error from the scripts
    that need it, and a `skipped` step in `bootstrap.py`."""

    def settings(self, tmp, value=None):
        path = Path(tmp) / "bootstrap.settings.json"
        data = {} if value is None else {"launchd_label_prefix": value}
        path.write_text(json.dumps(data))
        return path

    def test_a_configured_prefix_is_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lib.launchd_label_prefix(self.settings(tmp, PREFIX)), PREFIX)

    def test_a_trailing_dot_and_surrounding_space_are_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lib.launchd_label_prefix(self.settings(tmp, f"  {PREFIX}.  ")), PREFIX)

    def test_a_missing_settings_file_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(lib.PaperclipError) as err:
                lib.launchd_label_prefix(Path(tmp) / "nope.json")
        self.assertIn("bootstrap.settings.json", str(err.exception))

    def test_an_unset_key_is_a_clear_error_naming_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(lib.PaperclipError) as err:
                lib.launchd_label_prefix(self.settings(tmp))
        self.assertIn("launchd_label_prefix", str(err.exception))

    def test_a_placeholder_is_a_clear_error_not_a_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("<reverse.dns.prefix>", "com.<owner>", ""):
                with self.subTest(value=value):
                    with self.assertRaises(lib.PaperclipError) as err:
                        lib.launchd_label_prefix(self.settings(tmp, value))
                    self.assertIn("launchd_label_prefix", str(err.exception))

    def test_unreadable_json_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bootstrap.settings.json"
            path.write_text("{truncated")
            with self.assertRaises(lib.PaperclipError):
                lib.launchd_label_prefix(path)

    def test_the_shipped_settings_file_still_holds_a_placeholder(self):
        """The template ships unconfigured, so the real file must refuse."""
        with self.assertRaises(lib.PaperclipError):
            lib.launchd_label_prefix()


class WatchdogLabelTests(unittest.TestCase):
    def test_the_label_is_the_prefix_then_the_config_stem(self):
        self.assertEqual(no.watchdog_label("paperclip/orgs/second.json", prefix=PREFIX),
                         f"{PREFIX}.paperclip-watchdog.second")

    def test_each_config_gets_its_own_label(self):
        first = no.watchdog_label("paperclip/company.json", prefix=PREFIX)
        second = no.watchdog_label("paperclip/orgs/second.json", prefix=PREFIX)
        self.assertNotEqual(first, second)

    def test_no_prefix_configured_is_a_clear_error(self):
        with self.assertRaises(lib.PaperclipError):
            no.watchdog_label("paperclip/orgs/second.json")

    def test_the_plist_carries_the_label_the_repo_path_and_the_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = no.watchdog_plist(Path(tmp) / "orgs" / "second.json", repo=Path(tmp), prefix=PREFIX)
        self.assertIn(f"<string>{PREFIX}.paperclip-watchdog.second</string>", text)
        self.assertIn(f"{tmp}/scripts/paperclip-watchdog.py", text)
        self.assertIn("--config", text)
        self.assertIn("<integer>300</integer>", text)

    def test_the_plist_needs_a_prefix(self):
        with self.assertRaises(lib.PaperclipError):
            no.watchdog_plist("paperclip/orgs/second.json")

    def test_a_path_with_an_ampersand_is_escaped_for_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "a & b"
            text = no.watchdog_plist(root / "orgs" / "second.json", repo=root, prefix=PREFIX)
        self.assertIn("&amp;", text)
        self.assertNotIn("a & b", text)


class WatchdogTemplateTests(unittest.TestCase):
    """`scripts/paperclip-watchdog.plist.template` is the single-company plist a
    person installs by hand. It holds two substitution markers, the workbench
    path and the label prefix, both read from `bootstrap.settings.json`."""

    def test_the_tracked_template_holds_both_markers_and_no_absolute_path(self):
        """Every path and every label in the tracked file is a marker. An
        absolute path or a real reverse-DNS prefix left in it would name one
        machine and one practice."""
        text = (SCRIPTS / "paperclip-watchdog.plist.template").read_text()
        self.assertIn(no.LABEL_PREFIX_MARKER, text)
        self.assertIn(no.WORKBENCH_MARKER, text)
        home = str(Path.home())
        self.assertNotIn(home, text)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("<string>"):
                continue
            value = stripped[len("<string>"):].split("</string>")[0]
            if value.startswith("/"):
                self.assertIn(value, ("/usr/bin/python3", "/dev/null"), value)

    def test_rendering_puts_this_checkout_and_the_settings_prefix_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = no.render_watchdog_template(repo=Path(tmp), prefix=PREFIX)
        self.assertIn(f"<string>{PREFIX}.paperclip-watchdog</string>", text)
        self.assertIn(f"{tmp}/scripts/paperclip-watchdog.py", text)
        self.assertNotIn(no.LABEL_PREFIX_MARKER, text)
        self.assertNotIn(no.WORKBENCH_MARKER, text)

    def test_rendering_needs_a_prefix(self):
        with self.assertRaises(lib.PaperclipError):
            no.render_watchdog_template(repo=REPO)


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
        return {"id": f"new-{len(self.writes)}"}


GOAL = {"key": "wiki", "title": "Clear the wiki backlog", "description": "Done when ...",
        "level": "team", "status": "active", "ownerAgent": "engineering"}


class GoalTests(unittest.TestCase):
    def cfg(self, goals):
        return {"companyId": "co", "agents": [{"key": "engineering", "name": "Engineering lead"}], "goals": goals}

    def test_no_goals_key_plans_nothing_and_reads_nothing(self):
        self.assertEqual(pa._plan_goals({"companyId": "co", "agents": []}, FakeClient({}), {}), [])

    def test_missing_goal_is_created_with_its_owner(self):
        client = FakeClient({"/api/companies/co/goals": []})
        [action] = pa._plan_goals(self.cfg([GOAL]), client, {"engineering": "eng-id"})
        self.assertEqual((action.method, action.path), ("POST", "/api/companies/co/goals"))
        self.assertEqual(action.body, {"title": GOAL["title"], "description": "Done when ...",
                                       "level": "team", "status": "active", "ownerAgentId": "eng-id"})

    def test_matching_goal_plans_nothing(self):
        live = {"id": "g1", "title": GOAL["title"], "description": "Done when ...", "level": "team",
                "status": "active", "ownerAgentId": "eng-id", "parentId": None}
        client = FakeClient({"/api/companies/co/goals": [live]})
        self.assertEqual(pa._plan_goals(self.cfg([GOAL]), client, {"engineering": "eng-id"}), [])

    def test_changed_goal_is_patched_by_id(self):
        live = {"id": "g1", "title": GOAL["title"], "description": "old", "level": "team",
                "status": "planned", "ownerAgentId": "eng-id"}
        client = FakeClient({"/api/companies/co/goals": [live]})
        [action] = pa._plan_goals(self.cfg([GOAL]), client, {"engineering": "eng-id"})
        self.assertEqual((action.method, action.path), ("PATCH", "/api/goals/g1"))
        self.assertEqual(action.body, {"description": "Done when ...", "status": "active"})

    def test_goal_waits_for_an_owner_hired_in_this_pass(self):
        client = FakeClient({"/api/companies/co/goals": []})
        self.assertEqual(pa._plan_goals(self.cfg([GOAL]), client, {}), [])

    def test_goal_owner_that_is_not_configured_is_an_error(self):
        client = FakeClient({"/api/companies/co/goals": []})
        with self.assertRaises(lib.PaperclipError):
            pa._plan_goals(self.cfg([{**GOAL, "ownerAgent": "ghost"}]), client, {})

    def test_goal_with_no_owner_is_created_unowned(self):
        client = FakeClient({"/api/companies/co/goals": []})
        goal = {k: v for k, v in GOAL.items() if k != "ownerAgent"}
        [action] = pa._plan_goals(self.cfg([goal]), client, {})
        self.assertIsNone(action.body["ownerAgentId"])


class WatchdogStateTests(unittest.TestCase):
    def test_flag_wins(self):
        self.assertEqual(wd.state_path({"watchdog": {"stateFile": "x.json"}}, "/tmp/s.json"), Path("/tmp/s.json"))

    def test_config_names_the_state_file(self):
        self.assertEqual(wd.state_path({"watchdog": {"stateFile": ".paperclip/w2.json"}}, None),
                         wd.REPO_ROOT / ".paperclip" / "w2.json")

    def test_default_state_file_is_unchanged(self):
        self.assertEqual(wd.state_path({}, None), wd.REPO_ROOT / ".paperclip" / "watchdog-state.json")


class NewOrgTests(unittest.TestCase):
    OVERLAY = {"extends": "../company.json", "companyId": None,
               "company": {"name": "Second company", "description": "A test org"}}

    def test_create_plans_a_company_when_the_overlay_has_no_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, self.OVERLAY)
            client = FakeClient({"/api/companies": [{"id": "base-co", "name": "First company"}]})
            company_id, lines = no.ensure_company(path, client, apply=False)
        self.assertIsNone(company_id)
        self.assertEqual(client.writes, [])
        self.assertIn("create company 'Second company'", lines[0])

    def test_create_writes_the_new_id_back_into_the_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, self.OVERLAY)
            client = FakeClient({"/api/companies": []})
            company_id, _ = no.ensure_company(path, client, apply=True)
            saved = json.loads(path.read_text())
        self.assertEqual(company_id, "new-1")
        self.assertEqual(client.writes, [("POST", "/api/companies",
                                          {"name": "Second company", "description": "A test org"})])
        self.assertEqual(saved["companyId"], "new-1")
        self.assertEqual(saved["extends"], "../company.json")

    def test_a_live_company_with_the_name_is_never_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, self.OVERLAY)
            client = FakeClient({"/api/companies": [{"id": "live-1", "name": "Second company"}]})
            with self.assertRaises(lib.PaperclipError) as err:
                no.ensure_company(path, client, apply=True)
        self.assertIn("live-1", str(err.exception))
        self.assertEqual(client.writes, [])

    def test_a_name_match_is_an_error_even_on_a_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, self.OVERLAY)
            client = FakeClient({"/api/companies": [{"id": "live-1", "name": "Second company"}]})
            with self.assertRaises(lib.PaperclipError):
                no.ensure_company(path, client, apply=False)

    def test_an_overlay_with_an_id_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {**self.OVERLAY, "companyId": "have-1"})
            client = FakeClient({})
            company_id, lines = no.ensure_company(path, client, apply=True)
        self.assertEqual(company_id, "have-1")
        self.assertEqual(client.writes, [])

    def test_an_overlay_naming_no_company_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {"extends": "../company.json", "companyId": None})
            with self.assertRaises(lib.PaperclipError) as err:
                no.ensure_company(path, FakeClient({}), apply=True)
        self.assertIn("company.name", str(err.exception))

    def test_only_an_overlay_can_start_a_company(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "company.json"
            p.write_text(json.dumps({**BASE, "companyId": None}))
            with self.assertRaises(lib.PaperclipError):
                no.ensure_company(p, FakeClient({}), apply=True)

    def test_record_ids_writes_each_live_agent_id_by_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {**self.OVERLAY, "companyId": "new-co",
                                    "agentOverrides": {"scoper": {"runsPerDay": 250}}})
            client = FakeClient({"/api/companies/new-co/agents": [
                {"id": "s-9", "name": "Scoper"}, {"id": "e-9", "name": "Engineering lead"}]})
            lines = no.record_agent_ids(path, client)
            saved = json.loads(path.read_text())
        self.assertEqual(saved["agentOverrides"], {"scoper": {"runsPerDay": 250, "id": "s-9"},
                                                   "engineering": {"id": "e-9"}})
        self.assertEqual(len(lines), 2)

    def test_record_ids_puts_an_extra_agents_id_on_that_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {**self.OVERLAY, "companyId": "new-co",
                                    "extraAgents": [{"key": "engineering-twin", "id": None,
                                                     "name": "Engineering standby", "twinOf": "engineering"}]})
            client = FakeClient({"/api/companies/new-co/agents": [
                {"id": "s-9", "name": "Scoper"}, {"id": "e-9", "name": "Engineering lead"},
                {"id": "t-9", "name": "Engineering standby"}]})
            no.record_agent_ids(path, client)
            saved = json.loads(path.read_text())
        self.assertEqual(saved["extraAgents"][0]["id"], "t-9")
        self.assertNotIn("engineering-twin", saved.get("agentOverrides", {}))

    def test_recording_twice_writes_nothing_the_second_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, {**self.OVERLAY, "companyId": "new-co"})
            client = FakeClient({"/api/companies/new-co/agents": [
                {"id": "s-9", "name": "Scoper"}, {"id": "e-9", "name": "Engineering lead"}]})
            self.assertEqual(len(no.record_agent_ids(path, client)), 2)
            self.assertEqual(no.record_agent_ids(path, client), [])


class OverlayPatchTests(unittest.TestCase):
    """The overlay is read fresh after the network call and replaced atomically,
    so an edit made to it while a request was in flight survives, and a crash
    mid-write leaves the old file rather than a torn one."""

    OVERLAY = {"extends": "../company.json", "companyId": None, "company": {"name": "Second company"}}

    def test_a_concurrent_edit_to_another_key_survives_the_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, self.OVERLAY)

            class Editing(FakeClient):
                def send(self, method, p, body=None):
                    # While the create is "in flight", somebody edits the
                    # overlay: a key this patch does not set.
                    raw = json.loads(path.read_text())
                    raw["watchdog"] = {"stateFile": ".paperclip/added-mid-flight.json"}
                    path.write_text(json.dumps(raw))
                    return super().send(method, p, body)

            no.ensure_company(path, Editing({"/api/companies": []}), apply=True)
            saved = json.loads(path.read_text())
        self.assertEqual(saved["companyId"], "new-1")
        self.assertEqual(saved["watchdog"], {"stateFile": ".paperclip/added-mid-flight.json"})

    def test_the_patch_leaves_no_temp_file_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, self.OVERLAY)
            no.ensure_company(path, FakeClient({"/api/companies": []}), apply=True)
            names = sorted(p.name for p in path.parent.iterdir())
        self.assertEqual(names, ["new.json"])

    def test_a_patch_never_writes_the_resolved_base_into_the_overlay(self):
        """Only the overlay's own keys are written back. The base's agents,
        caps, and flags stay where they belong, in `company.json`."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_pair(tmp, self.OVERLAY)
            no.ensure_company(path, FakeClient({"/api/companies": []}), apply=True)
            saved = json.loads(path.read_text())
        self.assertEqual(set(saved), {"extends", "companyId", "company"})


class HelpTests(unittest.TestCase):
    def test_new_org_help_exits_zero(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            no.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--apply", out.getvalue())


if __name__ == "__main__":
    unittest.main()
