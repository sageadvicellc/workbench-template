"""Tests for scripts/bootstrap.py, the one entry point for a new machine.

No test runs a real command, calls a server, or writes outside a temp dir:
FakeRunner answers each command from a table and records every call.

Every value particular to one practice lives in `bootstrap.settings.json`, so
most tests here build a settings dict of their own and hand it to the context.
The shipped file is checked separately: every value in it is a placeholder, an
empty list, or a fixed argument list, and every key in it is read by a step.
"""

import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent

# The stand-in home directory inside each test's temp directory. It is not
# named `home`, because a temp path ending in that name then reads as an
# absolute home directory path, and `test_public_scrub.py` fails any tracked
# file that carries one.
FAKE_HOME = "stand-in-home"

sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("bootstrap", SCRIPTS / "bootstrap.py")
bs = importlib.util.module_from_spec(_spec)
sys.modules["bootstrap"] = bs
_spec.loader.exec_module(bs)


class FakeRunner:
    """`answers` maps a command's first words to (returncode, stdout)."""

    def __init__(self, answers, which=(), files=()):
        self.answers = answers
        self.which_set = set(which)
        self.files = set(files)
        self.calls = []

    def run(self, cmd, cwd=None):
        self.calls.append(tuple(cmd))
        for n in range(len(cmd), 0, -1):
            key = " ".join(str(c) for c in cmd[:n])
            if key in self.answers:
                return self.answers[key]
        return (127, "")

    def which(self, name):
        return name in self.which_set

    def exists(self, path):
        return str(path) in self.files


# A fully configured settings tree. No value here belongs to any practice; the
# names are invented for the tests.
CONFIGURED = {
    "workbench_path_in_templates": "/original/workbench",
    "brew_packages": ["tool-a", "tool-b"],
    "node_min": "24.11.0",
    "agent_cli": {
        "command": "agentcli",
        "min_version": "2.1.280",
        "version_args": ["--version"],
        "update_args": ["update"],
        "sign_in_note": "run agentcli once and sign in",
    },
    "packs": {
        "list_args": ["plugin", "list"],
        "marketplace_add_args": ["plugin", "marketplace", "add", "{name}"],
        "install_args": ["plugin", "install", "{name}"],
        "marketplaces": ["owner-one/market-one"],
        "install": ["pack-one@market-one"],
    },
    "repos": [{"path": "nested/repo-one", "remote": "owner-one/repo-one"}],
    "cli_tools": [{"name": "finder", "install": ["installer", "add", "finder"],
                   "after": [["finder", "pull"]]}],
    "launch_agents": [{"label": "org.example.refresh",
                       "template": "scripts/org.example.refresh.plist.template"}],
    "review_webhook": {"path": "~/.config/reviews/webhook",
                       "how": ["Open the chat app and copy the webhook URL"]},
}

HEALTHY = {
    "xcode-select -p": (0, "/Library/Developer/CommandLineTools\n"),
    "node --version": (0, "v24.11.0\n"),
    "agentcli --version": (0, "2.1.283 (agentcli)\n"),
    "gh auth status": (0, "Logged in\n"),
    "git config --get core.hooksPath": (0, ".githooks\n"),
    "brew list --versions tool-a tool-b": (0, "tool-a 2\ntool-b 1\n"),
    "agentcli plugin list": (0, "pack-one@market-one\n"),
    "launchctl list": (0, "-\t0\torg.example.refresh\n"),
    "pmset -g": (0, " sleep                0\n"),
}


def settings_accessor(key):
    """A pattern that matches a real read of this settings key: the key, or a
    dotted path starting with it, quoted inside a call to `get`,
    `unconfigured`, or `first_unconfigured`. Those three are the only ways
    `bootstrap.py` reads a setting."""
    return re.compile(r"\.(?:get|unconfigured|first_unconfigured)\("
                      rf'[^)]*"{re.escape(key)}(?:\.[A-Za-z_]+)*"')


def settings(overrides=None, base=CONFIGURED):
    """A deep-ish copy of `base` with `overrides` merged one level down."""
    data = json.loads(json.dumps(base))
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    return bs.Settings(data)


def ctx(tmp, runner, fix=False, config=None, yes=True):
    """A context for a test. `yes` skips the settings-commands prompt, which is
    what every test but `ApprovalTests` wants: no test may read stdin."""
    return bs.Context(repo=Path(tmp), home=Path(tmp) / FAKE_HOME, runner=runner, fix=fix,
                      settings=config if config is not None else settings(), assume_yes=yes)


class VersionTests(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(bs.at_least("v24.11.0", "24.11.0"))
        self.assertTrue(bs.at_least("2.1.283 (agentcli)", "2.1.280"))
        self.assertFalse(bs.at_least("2.1.257", "2.1.280"))
        self.assertFalse(bs.at_least("v22.3.1", "24.11.0"))
        self.assertFalse(bs.at_least("", "1.0.0"))


class PlanTests(unittest.TestCase):
    # Every step this script runs, in order. Pinned here because a step that
    # depends on software this template does not ship would leave a reader with
    # a report they cannot act on.
    EXPECTED = ["xcode-clt", "homebrew", "brew-packages", "node", "agent-cli", "gh-auth",
                "git-hooks", "repos", "packs", "cli-tools", "launch-agents",
                "review-webhook", "always-on"]

    def test_the_step_list_is_exactly_the_documented_one(self):
        self.assertEqual([s.id for s in bs.STEPS], self.EXPECTED)

    def test_every_step_has_an_id_a_title_and_a_way_forward(self):
        ids = [s.id for s in bs.STEPS]
        self.assertEqual(len(ids), len(set(ids)))
        for step in bs.STEPS:
            self.assertTrue(step.title)
            for need in step.needs:
                self.assertIn(need, ids[:ids.index(step.id)], f"{step.id} needs {need}, which must run first")

    def test_no_step_title_names_a_version_or_a_practice(self):
        for step in bs.STEPS:
            self.assertNotRegex(step.title, r"\d+\.\d+", f"{step.id} pins a version in its title")


class StatusTests(unittest.TestCase):
    """One test per status the runner can return."""

    def test_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY)), only={"git-hooks"})
        self.assertEqual(result.status, "ok")

    def test_manual_and_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({"xcode-select -p": (2, "")})
            results = bs.run_steps(ctx(tmp, runner), only={"xcode-clt", "homebrew"})
        self.assertEqual(results[0].status, "manual")
        self.assertIn("xcode-select --install", results[0].commands)
        self.assertEqual(results[1].status, "blocked")
        self.assertIn("xcode-clt", results[1].detail)

    def test_fixable_in_check_mode_and_no_fix_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({**HEALTHY, "git config --get core.hooksPath": (1, "")}, which={"brew"})
            [result] = bs.run_steps(ctx(tmp, runner, fix=False), only={"git-hooks"})
        self.assertEqual(result.status, "fixable")
        self.assertNotIn(("git", "config", "core.hooksPath", ".githooks"), runner.calls)
        self.assertTrue(any(c.endswith("&& git config core.hooksPath .githooks") for c in result.commands))

    def test_fixed_after_the_fix_runs_and_the_recheck_passes(self):
        answers = {**HEALTHY, "git config --get core.hooksPath": (1, ""), "git config core.hooksPath": (0, "")}

        class Flip(FakeRunner):
            def run(self, cmd, cwd=None):
                if tuple(cmd) == ("git", "config", "core.hooksPath", ".githooks"):
                    self.answers["git config --get core.hooksPath"] = (0, ".githooks\n")
                return super().run(cmd, cwd)

        with tempfile.TemporaryDirectory() as tmp:
            [result] = bs.run_steps(ctx(tmp, Flip(answers), fix=True), only={"git-hooks"})
        self.assertEqual(result.status, "fixed")

    def test_failed_when_a_fix_does_not_take(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({**HEALTHY, "git config --get core.hooksPath": (1, ""),
                                 "git config core.hooksPath": (1, "error: could not lock config file")})
            [result] = bs.run_steps(ctx(tmp, runner, fix=True), only={"git-hooks"})
        self.assertEqual(result.status, "failed")
        self.assertIn("could not lock", result.detail)

    def test_failed_when_a_write_cannot_land(self):
        """A `Write` that raises is the same kind of failure as a command that
        returns non-zero: one failed step, and every other step still runs. It
        used to escape and kill the whole run."""
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "scripts" / "org.example.refresh.plist.template"
            template.parent.mkdir(parents=True)
            template.write_text("<string>/original/workbench/x</string>\n")
            (Path(tmp) / FAKE_HOME).write_text("a file where the home directory should be")
            runner = FakeRunner({**HEALTHY, "launchctl list": (0, "-\t0\tsomething.else\n")})
            results = bs.run_steps(ctx(tmp, runner, fix=True), only={"launch-agents", "always-on"})
        self.assertEqual([r.status for r in results], ["failed", "ok"])
        self.assertIn("write ", results[0].detail)

    def test_failed_when_a_check_raises(self):
        def boom(_):
            raise RuntimeError("no")

        with tempfile.TemporaryDirectory() as tmp:
            step = bs.Step("boom", "Boom", boom)
            result = bs._run_one(step, ctx(tmp, FakeRunner(HEALTHY)))
        self.assertEqual(result.status, "failed")
        self.assertIn("RuntimeError", result.detail)

    def test_skipped_when_a_settings_list_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = settings({"brew_packages": []})
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY), config=config), only={"brew-packages"})
        self.assertEqual(result.status, "skipped")
        self.assertIn("brew_packages", result.detail)

    def test_skipped_when_a_settings_value_is_a_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = settings({"node_min": "<x.y.z>"})
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY), config=config), only={"node"})
        self.assertEqual(result.status, "skipped")
        self.assertIn("node_min", result.detail)

    def test_a_skipped_prerequisite_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = settings({"brew_packages": []})
            results = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY), config=config),
                                   only={"brew-packages", "gh-auth"})
        self.assertEqual([r.status for r in results], ["skipped", "ok"])


class SettingsTests(unittest.TestCase):
    def test_the_shipped_file_parses_and_holds_a_placeholder_in_every_key_that_takes_one(self):
        data = json.loads((ROOT / "bootstrap.settings.json").read_text())
        found = set(bs.placeholder_keys(data))
        expected = {
            "workbench_path_in_templates",
            "brew_packages[0]",
            "node_min",
            "agent_cli.command",
            "agent_cli.min_version",
            "agent_cli.sign_in_note",
            "packs.marketplaces[0]",
            "packs.install[0]",
            "repos[0].path",
            "repos[0].remote",
            "cli_tools[0].name",
            "cli_tools[0].install[0]",
            "cli_tools[0].install[1]",
            "launch_agents[0].label",
            "launch_agents[0].template",
            "review_webhook.path",
            "review_webhook.how[0]",
        }
        self.assertEqual(found, expected)

    def test_the_shipped_file_has_every_key_the_documented_schema_names(self):
        data = json.loads((ROOT / "bootstrap.settings.json").read_text())
        self.assertEqual(set(data), {
            "workbench_path_in_templates", "brew_packages", "node_min", "agent_cli",
            "packs", "repos", "cli_tools", "launch_agents", "review_webhook"})
        self.assertEqual(set(data["agent_cli"]),
                         {"command", "min_version", "version_args", "update_args", "sign_in_note"})
        self.assertEqual(set(data["packs"]), {"list_args", "marketplace_add_args", "install_args",
                                              "marketplaces", "install"})
        self.assertEqual(set(data["review_webhook"]), {"path", "how"})

    def test_every_key_in_the_shipped_file_is_read_by_a_step(self):
        """A settings key nothing reads is a question the reader answers for
        nothing. The match is anchored to a settings accessor call, because a
        key named only in a comment or a docstring is not read by anything."""
        data = json.loads((ROOT / "bootstrap.settings.json").read_text())
        source = (SCRIPTS / "bootstrap.py").read_text()
        for key in data:
            with self.subTest(key=key):
                self.assertRegex(source, settings_accessor(key),
                                 f"{key} is in the settings file and no step reads it")

    def test_a_key_named_only_in_a_comment_does_not_count_as_read(self):
        """The check above used to match the key name anywhere in the file, so a
        key that was named in a comment and read nowhere passed it."""
        pattern = settings_accessor("node_min")
        self.assertIsNone(pattern.search("# node_min is read by the node step\n"))
        self.assertIsNone(pattern.search('"""node_min: the minimum version."""\n'))
        self.assertIsNotNone(pattern.search('minimum = str(ctx.settings.get("node_min"))'))
        self.assertIsNotNone(pattern.search('ctx.settings.unconfigured("node_min")'))
        self.assertIsNotNone(pattern.search(
            'ctx.settings.first_unconfigured("launch_agents", "node_min")'))
        self.assertIsNotNone(pattern.search('ctx.settings.get("node_min.floor")'))

    def test_the_shipped_file_leaves_every_step_skipped_and_never_raises(self):
        data = json.loads((ROOT / "bootstrap.settings.json").read_text())
        config = bs.Settings(data)
        driven = {"brew-packages", "node", "agent-cli", "repos", "packs", "cli-tools",
                  "launch-agents", "review-webhook"}
        with tempfile.TemporaryDirectory() as tmp:
            results = bs.run_steps(ctx(tmp, FakeRunner({}), config=config), only=driven)
        raised = [r for r in results if "raised" in r.detail]
        self.assertEqual(raised, [])
        self.assertEqual(len(results), len(driven))
        for result in results:
            self.assertEqual(result.status, "skipped", f"{result.id}: {result.detail}")

    def test_a_missing_settings_file_is_a_reason_not_a_traceback(self):
        config = bs.Settings.load(Path("/nonexistent/bootstrap.settings.json"))
        self.assertTrue(config.error)
        self.assertIsNotNone(config.unconfigured("node_min"))
        with tempfile.TemporaryDirectory() as tmp:
            [result] = bs.run_steps(ctx(tmp, FakeRunner({}), config=config), only={"node"})
        self.assertEqual(result.status, "skipped")

    def test_placeholder_detection(self):
        self.assertTrue(bs.has_placeholder("<owner>/<repo>"))
        self.assertTrue(bs.has_placeholder(["fine", "<not fine>"]))
        self.assertTrue(bs.has_placeholder({"a": {"b": "<x>"}}))
        self.assertFalse(bs.has_placeholder("owner/repo"))
        self.assertFalse(bs.has_placeholder(False))
        self.assertFalse(bs.has_placeholder(["--version"]))

    def test_a_configured_key_is_never_reported_unconfigured(self):
        config = settings()
        for key in ("brew_packages", "node_min", "agent_cli.command", "packs.install",
                    "repos", "cli_tools", "launch_agents", "review_webhook.path"):
            self.assertIsNone(config.unconfigured(key), key)


class ExitCodeTests(unittest.TestCase):
    def test_ok_fixed_and_skipped_leave_the_exit_code_zero(self):
        results = [bs.Result("a", "A", "ok"), bs.Result("b", "B", "fixed"),
                   bs.Result("c", "C", "skipped", "repos is empty")]
        self.assertEqual(bs.exit_code(results), 0)

    def test_a_skipped_step_alone_leaves_the_exit_code_zero(self):
        self.assertEqual(bs.exit_code([bs.Result("c", "C", "skipped", "repos is empty")]), 0)

    def test_manual_fixable_failed_and_blocked_each_make_it_non_zero(self):
        for status in ("manual", "fixable", "failed", "blocked"):
            self.assertEqual(bs.exit_code([bs.Result("a", "A", status)]), 1, status)


class PackTests(unittest.TestCase):
    def test_name_is_substituted_into_every_pack_argument_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({**HEALTHY, "agentcli plugin list": (0, "")})
            [result] = bs.run_steps(ctx(tmp, runner), only={"packs"})
        self.assertEqual(result.status, "fixable")
        self.assertIn("agentcli plugin marketplace add owner-one/market-one", result.commands)
        self.assertIn("agentcli plugin install pack-one@market-one", result.commands)
        self.assertNotIn("{name}", " ".join(result.commands))

    def test_installed_packs_report_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY)), only={"packs"})
        self.assertEqual(result.status, "ok")

    def test_the_step_is_skipped_when_the_command_is_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = settings({"agent_cli": {"command": "<the harness command>"}})
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY), config=config), only={"packs"})
        self.assertEqual(result.status, "skipped")
        self.assertIn("agent_cli.command", result.detail)


class AgentCliTests(unittest.TestCase):
    def test_an_old_version_is_updated_with_the_update_args_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({**HEALTHY, "agentcli --version": (0, "2.1.257\n")})
            [result] = bs.run_steps(ctx(tmp, runner), only={"agent-cli"})
        self.assertEqual(result.status, "fixable")
        self.assertIn("agentcli update", result.commands)

    def test_a_missing_command_is_manual_and_repeats_the_sign_in_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({**HEALTHY, "agentcli --version": (127, "")})
            [result] = bs.run_steps(ctx(tmp, runner), only={"agent-cli"})
        self.assertEqual(result.status, "manual")
        self.assertIn("run agentcli once and sign in", result.commands)


class RepoTests(unittest.TestCase):
    def test_a_relative_path_a_home_path_and_an_absolute_path(self):
        repos = [{"path": "nested/repo-one", "remote": "owner-one/repo-one"},
                 {"path": "~/code/repo-two", "remote": "owner-one/repo-two"},
                 {"path": "/opt/repo-three", "remote": "owner-one/repo-three"}]
        with tempfile.TemporaryDirectory() as tmp:
            config = settings({"repos": repos})
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY), config=config), only={"repos"})
        self.assertEqual(result.status, "fixable")
        self.assertIn(f"gh repo clone owner-one/repo-one {tmp}/nested/repo-one", result.commands)
        self.assertIn(f"gh repo clone owner-one/repo-two {tmp}/{FAKE_HOME}/code/repo-two", result.commands)
        self.assertIn("gh repo clone owner-one/repo-three /opt/repo-three", result.commands)

    def test_a_cloned_repo_reports_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(HEALTHY, files={f"{tmp}/nested/repo-one"})
            [result] = bs.run_steps(ctx(tmp, runner), only={"repos"})
        self.assertEqual(result.status, "ok")


class CliToolTests(unittest.TestCase):
    def test_a_missing_tool_is_installed_and_its_after_commands_follow(self):
        with tempfile.TemporaryDirectory() as tmp:
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY)), only={"cli-tools"})
        self.assertEqual(result.status, "fixable")
        self.assertEqual(result.commands, ["installer add finder", "finder pull"])

    def test_a_present_tool_reports_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(HEALTHY, which={"finder"})
            [result] = bs.run_steps(ctx(tmp, runner), only={"cli-tools"})
        self.assertEqual(result.status, "ok")


class LaunchAgentTests(unittest.TestCase):
    def template(self, tmp, name="org.example.refresh.plist.template"):
        path = Path(tmp) / "scripts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<string>/original/workbench/scripts/refresh.py</string>\n")
        return path

    def test_a_template_is_rendered_with_this_checkout_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.template(tmp)
            text = bs.render_template(path, Path("/Volumes/Studio/workbench"), "/original/workbench")
        self.assertIn("/Volumes/Studio/workbench/scripts/refresh.py", text)
        self.assertNotIn("/original/workbench/scripts", text)

    def test_a_missing_agent_is_written_and_bootstrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.template(tmp)
            runner = FakeRunner({**HEALTHY, "launchctl list": (0, "-\t0\tsomething.else\n")})
            [result] = bs.run_steps(ctx(tmp, runner), only={"launch-agents"})
        self.assertEqual(result.status, "fixable")
        self.assertTrue(any(c.startswith("write ") and c.endswith("org.example.refresh.plist")
                            for c in result.commands))
        self.assertTrue(any("launchctl bootstrap" in c for c in result.commands))

    def test_a_loaded_agent_reports_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.template(tmp)
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY)), only={"launch-agents"})
        self.assertEqual(result.status, "ok")

    def test_a_missing_template_is_skipped_and_names_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY)), only={"launch-agents"})
        self.assertEqual(result.status, "skipped")
        self.assertIn("org.example.refresh.plist.template", result.detail)

    def test_a_label_that_leaves_the_launch_agents_directory_is_refused(self):
        """A label is joined into a path. A label holding `../` would write the
        plist outside `~/Library/LaunchAgents`, and `launchctl bootstrap` would
        then run on it."""
        with tempfile.TemporaryDirectory() as tmp:
            self.template(tmp)
            config = settings({"launch_agents": [
                {"label": "../../../../tmp/escaped", "template": "scripts/org.example.refresh.plist.template"}]})
            runner = FakeRunner({**HEALTHY, "launchctl list": (0, "")})
            [result] = bs.run_steps(ctx(tmp, runner, fix=True, config=config), only={"launch-agents"})
        self.assertEqual(result.status, "failed")
        self.assertIn("launchd label", result.detail)
        self.assertFalse((Path(tmp) / FAKE_HOME / "Library").exists())

    def test_the_label_rule_accepts_a_reverse_dns_label_and_refuses_the_rest(self):
        self.assertEqual(bs.check_label("org.example.work_bench-1"), "org.example.work_bench-1")
        for bad in ("../escaped", "with space", "semi;colon", "", "a/b", "sub/../x"):
            with self.assertRaises(bs.BootstrapError, msg=bad):
                bs.check_label(bad)

    def test_a_written_launch_agent_is_readable_only_by_its_owner(self):
        """No credential is in the template today. Mode 600 is set before one
        is, because a plist under `~/Library/LaunchAgents` is a plausible place
        for one and the default umask leaves it world-readable."""
        with tempfile.TemporaryDirectory() as tmp:
            self.template(tmp)
            runner = FakeRunner({**HEALTHY, "launchctl list": (0, ""), "launchctl bootstrap": (0, "")})
            bs.run_steps(ctx(tmp, runner, fix=True), only={"launch-agents"})
            plist = Path(tmp) / FAKE_HOME / "Library" / "LaunchAgents" / "org.example.refresh.plist"
            self.assertTrue(plist.is_file())
            self.assertEqual(plist.stat().st_mode & 0o777, 0o600)

    def test_an_unconfigured_workbench_path_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.template(tmp)
            config = settings({"workbench_path_in_templates": "<absolute path of this workbench>"})
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY), config=config), only={"launch-agents"})
        self.assertEqual(result.status, "skipped")
        self.assertIn("workbench_path_in_templates", result.detail)


class ReviewWebhookTests(unittest.TestCase):
    def test_a_missing_webhook_is_manual_and_never_prints_a_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY)), only={"review-webhook"})
        self.assertEqual(result.status, "manual")
        self.assertEqual(result.commands, ["Open the chat app and copy the webhook URL"])
        self.assertIn(f"{tmp}/{FAKE_HOME}/.config/reviews/webhook", result.detail)

    def test_a_present_webhook_reports_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(HEALTHY, files={f"{tmp}/{FAKE_HOME}/.config/reviews/webhook"})
            [result] = bs.run_steps(ctx(tmp, runner), only={"review-webhook"})
        self.assertEqual(result.status, "ok")

    def test_an_unconfigured_path_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = settings({"review_webhook": {"path": "<absolute path>"}})
            [result] = bs.run_steps(ctx(tmp, FakeRunner(HEALTHY), config=config), only={"review-webhook"})
        self.assertEqual(result.status, "skipped")
        self.assertIn("review_webhook.path", result.detail)


class ApprovalTests(unittest.TestCase):
    """`bootstrap.settings.json` supplies whole argument vectors that this
    script executes. A reader who clones a derived workbench has not read them,
    so a run prints them and asks once before it runs the first command."""

    def run_with(self, answers, only, tmp, replies, config=None):
        runner = FakeRunner(answers)
        context = ctx(tmp, runner, fix=True, yes=False, config=config)
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return replies.pop(0)

        context.ask = ask
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            results = bs.run_steps(context, only=only)
        return results, runner, asked, out.getvalue()

    def test_the_first_command_prints_every_settings_argv_and_asks(self):
        answers = {**HEALTHY, "git config --get core.hooksPath": (1, ""), "git config core.hooksPath": (0, "")}
        with tempfile.TemporaryDirectory() as tmp:
            _, _, asked, out = self.run_with(answers, {"git-hooks"}, tmp, ["y"])
        self.assertEqual(len(asked), 1)
        self.assertIn("installer add finder", out)
        self.assertIn("finder pull", out)
        self.assertIn("agentcli plugin install", out)
        self.assertIn("owner-one/repo-one", out)
        self.assertIn("bootstrap.settings.json", out)

    def test_a_refusal_runs_nothing_and_fails_the_step(self):
        answers = {**HEALTHY, "git config --get core.hooksPath": (1, "")}
        with tempfile.TemporaryDirectory() as tmp:
            results, runner, _, _ = self.run_with(answers, {"git-hooks"}, tmp, ["n"])
        self.assertEqual(results[0].status, "failed")
        self.assertIn("not approved", results[0].detail)
        self.assertNotIn(("git", "config", "core.hooksPath", ".githooks"), runner.calls)

    def test_one_run_asks_once_however_many_steps_have_fixes(self):
        answers = {**HEALTHY, "git config --get core.hooksPath": (1, ""), "git config core.hooksPath": (0, ""),
                   "agentcli plugin list": (0, "")}
        with tempfile.TemporaryDirectory() as tmp:
            _, _, asked, _ = self.run_with(answers, {"git-hooks", "packs"}, tmp, ["y"])
        self.assertEqual(len(asked), 1)

    def test_a_refusal_holds_for_every_later_step_too(self):
        answers = {**HEALTHY, "git config --get core.hooksPath": (1, ""), "agentcli plugin list": (0, "")}
        with tempfile.TemporaryDirectory() as tmp:
            results, runner, asked, _ = self.run_with(answers, {"git-hooks", "packs"}, tmp, ["n"])
        self.assertEqual([r.status for r in results], ["failed", "failed"])
        self.assertEqual(len(asked), 1)
        self.assertNotIn(("agentcli", "plugin", "install", "pack-one@market-one"), runner.calls)

    def test_a_closed_stdin_reads_as_no(self):
        """An unattended run with no `--yes` must not hang or crash. It stops."""
        def ask(_):
            raise EOFError

        answers = {**HEALTHY, "git config --get core.hooksPath": (1, "")}
        with tempfile.TemporaryDirectory() as tmp:
            context = ctx(tmp, FakeRunner(answers), fix=True, yes=False)
            context.ask = ask
            with contextlib.redirect_stdout(io.StringIO()):
                [result] = bs.run_steps(context, only={"git-hooks"})
        self.assertEqual(result.status, "failed")
        self.assertIn("not approved", result.detail)

    def test_assume_yes_never_asks(self):
        def ask(_):
            raise AssertionError("a run with --yes must not ask")

        answers = {**HEALTHY, "git config --get core.hooksPath": (1, ""), "git config core.hooksPath": (0, "")}
        with tempfile.TemporaryDirectory() as tmp:
            context = ctx(tmp, FakeRunner(answers), fix=True, yes=True)
            context.ask = ask
            with contextlib.redirect_stdout(io.StringIO()):
                bs.run_steps(context, only={"git-hooks"})

    def test_check_mode_never_asks_because_it_runs_nothing(self):
        def ask(_):
            raise AssertionError("--check must not ask")

        answers = {**HEALTHY, "git config --get core.hooksPath": (1, "")}
        with tempfile.TemporaryDirectory() as tmp:
            context = ctx(tmp, FakeRunner(answers), fix=False, yes=False)
            context.ask = ask
            with contextlib.redirect_stdout(io.StringIO()):
                [result] = bs.run_steps(context, only={"git-hooks"})
        self.assertEqual(result.status, "fixable")

    def test_settings_argv_names_every_vector_settings_supply(self):
        vectors = [" ".join(v) for v in bs.settings_argv(settings())]
        self.assertIn("installer add finder", vectors)
        self.assertIn("finder pull", vectors)
        self.assertIn("agentcli plugin install {name}", vectors)
        self.assertIn("agentcli plugin marketplace add {name}", vectors)
        self.assertIn("gh repo clone owner-one/repo-one", vectors)

    def test_settings_argv_is_empty_when_nothing_is_configured(self):
        self.assertEqual(bs.settings_argv(bs.Settings({})), [])


class OutputTests(unittest.TestCase):
    def test_json_report_is_parseable_and_counts_every_status(self):
        results = [bs.Result("a", "A", "ok", "fine"),
                   bs.Result("b", "B", "manual", "do it", ["run this"]),
                   bs.Result("c", "C", "skipped", "repos is empty")]
        data = json.loads(bs.report_json(results, ["node_min"]))
        self.assertEqual(data["summary"], {"ok": 1, "manual": 1, "skipped": 1})
        self.assertEqual(data["steps"][1]["commands"], ["run this"])
        self.assertEqual(data["placeholders"], ["node_min"])

    def test_text_report_ends_with_numbered_next_steps(self):
        results = [bs.Result("a", "A", "ok", "fine"),
                   bs.Result("b", "B", "manual", "do it", ["run this"]),
                   bs.Result("c", "C", "blocked", "waits for b")]
        text = bs.report_text(results)
        self.assertIn("1. B", text)
        self.assertIn("run this", text)
        self.assertIn("then rerun ./bootstrap.sh", text)

    def test_text_report_last_line_names_every_unconfigured_key(self):
        results = [bs.Result("a", "A", "skipped", "node_min is unset")]
        text = bs.report_text(results, ["node_min", "repos[0].remote"])
        self.assertIn("node_min", text.splitlines()[-1])
        self.assertIn("repos[0].remote", text.splitlines()[-1])

    def test_text_report_says_so_when_nothing_is_unconfigured(self):
        text = bs.report_text([bs.Result("a", "A", "ok", "fine")], [])
        self.assertIn("bootstrap.settings.json", text.splitlines()[-1])


class MainTests(unittest.TestCase):
    def run_main(self, argv, context):
        """`main`, with its report captured rather than printed."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = bs.main(argv, ctx=context)
        return code, out.getvalue()

    def test_an_unknown_step_id_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as caught:
                self.run_main(["--check", "--only", "not-a-step"], ctx(tmp, FakeRunner(HEALTHY)))
        self.assertNotEqual(caught.exception.code, 0)

    def test_json_output_parses_and_a_skipped_only_run_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = settings({"brew_packages": []})
            code, out = self.run_main(["--check", "--json", "--only", "brew-packages"],
                                      ctx(tmp, FakeRunner(HEALTHY), config=config))
        data = json.loads(out)
        self.assertEqual(data["summary"], {"skipped": 1})
        self.assertEqual(code, 0)

    def test_a_manual_step_makes_the_exit_code_non_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({"xcode-select -p": (2, "")})
            code, _ = self.run_main(["--check", "--only", "xcode-clt"], ctx(tmp, runner))
        self.assertEqual(code, 1)

    def test_the_prompt_is_the_default_and_yes_turns_it_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ctx(tmp, FakeRunner(HEALTHY), yes=False)
            self.run_main(["--check", "--only", "always-on"], context)
            self.assertFalse(context.assume_yes)
            self.run_main(["--check", "--yes", "--only", "always-on"], context)
            self.assertTrue(context.assume_yes)

    def test_check_mode_never_flips_the_context_into_fixing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner({**HEALTHY, "git config --get core.hooksPath": (1, "")})
            context = ctx(tmp, runner, fix=True)
            self.run_main(["--check", "--only", "git-hooks"], context)
        self.assertNotIn(("git", "config", "core.hooksPath", ".githooks"), runner.calls)


if __name__ == "__main__":
    unittest.main()
