"""Tests for the generic `paperclip/` scaffold this template ships.

Run with:

    uv run --quiet --with pytest python -m pytest scripts/tests -q

These tests read the real files in `paperclip/`, not a fixture. The scaffold
is the shape a setup pass fills in, so the checks are about shape and safety:
every file is present, every switch sits at its safe value, every run cap is a
real positive number, and nothing carries an identifier or a name from the
practice this template was generalised from.
"""

import json
import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
PAPERCLIP = REPO / "paperclip"
sys.path.insert(0, str(SCRIPTS))

import paperclip_lib as lib  # noqa: E402

EXPECTED_PATHS = [
    "README.md",
    "company.json",
    "ideas.md",
    "wake-prompt.md",
    "orgs/example.json",
    "agents/chief-of-staff/AGENTS.md",
    "agents/lead/AGENTS.md",
    "subagents/builder.md",
    "subagents/reviewer.md",
    "souls/README.md",
]

# A file under `paperclip/` is markdown or JSON. Anything else is not scanned.
SCANNED_SUFFIXES = {".md", ".json"}

UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                  r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

# Names from the practice this scaffold was generalised from. A generic
# template that carries one of them is not generic. Each is matched on a word
# boundary, so an ordinary word that contains one, such as "usage", passes.
BANNED_WORDS = [
    "coda", "emery", "aspen", "darcey", "clay", "quinn", "rowan",
    "atlas", "atom", "virginia", "pixel", "hanna", "sage",
]
BANNED_WORD = re.compile(r"\b(" + "|".join(BANNED_WORDS) + r")\b", re.IGNORECASE)

# Substrings that need no boundary: a repository owner, and an outward channel.
BANNED_SUBSTRINGS = ["sageadvicellc", "hannasage", "discord.com/api/webhooks"]

DISCLAIMER = ("This block shapes tone only: it grants no channel, it applies if and "
              "when you speak in Discord, and the shared contract still forbids "
              "sending any message through a connector.")

VOICE_FILES = ["agents/chief-of-staff/AGENTS.md", "agents/lead/AGENTS.md",
               "subagents/builder.md", "subagents/reviewer.md"]


def scanned_files():
    return sorted(p for p in PAPERCLIP.rglob("*")
                  if p.is_file() and p.suffix in SCANNED_SUFFIXES)


def squash(text):
    """One space between words, so a sentence wrapped over lines still matches."""
    return " ".join(text.split())


class LayoutTests(unittest.TestCase):
    def test_every_expected_path_exists(self):
        for rel in EXPECTED_PATHS:
            with self.subTest(path=rel):
                self.assertTrue((PAPERCLIP / rel).is_file(), f"paperclip/{rel} is missing")

    def test_the_two_json_files_parse(self):
        for rel in ("company.json", "orgs/example.json"):
            with self.subTest(path=rel):
                json.loads((PAPERCLIP / rel).read_text())

    def test_every_instructions_file_named_by_the_config_exists(self):
        cfg = json.loads((PAPERCLIP / "company.json").read_text())
        for agent in cfg["agents"]:
            with self.subTest(agent=agent["key"]):
                self.assertTrue((REPO / agent["instructionsFile"]).is_file())
        self.assertTrue((REPO / cfg["defaults"]["wakePromptFile"]).is_file())


class SafetySettingTests(unittest.TestCase):
    """Each switch below stops the server from making work without a person.
    The scaffold ships them safe, so a clone that is never edited is still
    safe."""

    def setUp(self):
        self.cfg = json.loads((PAPERCLIP / "company.json").read_text())

    def test_a_new_agent_needs_board_approval(self):
        self.assertIs(self.cfg["company"]["requireBoardApprovalForNewAgents"], True)

    def test_the_three_experimental_switches_are_off(self):
        experimental = self.cfg["experimental"]
        for key in ("enableIssueGraphLivenessAutoRecovery", "enableTaskWatchdogs",
                    "enableIssuePlanDecompositions"):
            with self.subTest(switch=key):
                self.assertIs(experimental[key], False)

    def test_the_heartbeat_timer_is_off(self):
        self.assertIs(self.cfg["defaults"]["runtimeConfig"]["heartbeat"]["enabled"], False)

    def test_the_three_default_permissions_are_off(self):
        permissions = self.cfg["defaults"]["permissions"]
        for key in ("canCreateAgents", "canCreateSkills", "canAssignTasks"):
            with self.subTest(permission=key):
                self.assertIs(permissions[key], False)

    def test_permission_skip_is_written_out_and_false_everywhere(self):
        """Some adapters default this to `true`, so the scaffold states it."""
        adapters = self.cfg["defaults"]["adapters"]
        written = [name for name, profile in adapters.items()
                   if "dangerouslySkipPermissions" in profile]
        self.assertTrue(written, "no adapter profile states dangerouslySkipPermissions")
        for name in written:
            with self.subTest(adapter=name):
                self.assertIs(adapters[name]["dangerouslySkipPermissions"], False)

    def test_the_wake_prompt_replaces_the_adapter_default(self):
        self.assertEqual(self.cfg["defaults"]["wakePromptFile"], "paperclip/wake-prompt.md")

    def test_no_agent_holds_the_ceo_role(self):
        for agent in self.cfg["agents"]:
            with self.subTest(agent=agent["key"]):
                self.assertNotEqual(agent.get("role"), "ceo")

    def test_two_example_agents_one_chief_of_staff_and_one_lead(self):
        self.assertEqual([a["key"] for a in self.cfg["agents"]], ["chief-of-staff", "lead"])

    def test_every_agent_id_is_null_or_a_placeholder(self):
        for agent in self.cfg["agents"]:
            with self.subTest(agent=agent["key"]):
                agent_id = agent.get("id")
                self.assertTrue(agent_id is None or lib.PLACEHOLDER.search(agent_id),
                                f"{agent['key']} carries a literal id: {agent_id!r}")

    def test_the_company_id_is_a_placeholder(self):
        self.assertTrue(lib.PLACEHOLDER.search(self.cfg["companyId"]))


class RunCapTests(unittest.TestCase):
    """A cap of `0` reads as "no cap configured" at every enforcement site, so
    it disables the breaker instead of stopping the agent. An example that
    shipped one would teach the wrong shape."""

    CAP_KEYS = ("runsPerDay", "harnessTotal", "maxConcurrentRuns")

    def caps_in(self, node, trail="example.json"):
        """Every cap key anywhere in the overlay, with the path that found it."""
        found = []
        if isinstance(node, dict):
            for key, value in node.items():
                where = f"{trail}.{key}"
                if key in self.CAP_KEYS:
                    found.append((where, value))
                elif key == "agents" and isinstance(value, dict):
                    found.extend((f"{where}.{k}", v) for k, v in value.items())
                else:
                    found.extend(self.caps_in(value, where))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                found.extend(self.caps_in(value, f"{trail}[{i}]"))
        return found

    def test_the_overlay_has_caps_to_check(self):
        caps = self.caps_in(json.loads((PAPERCLIP / "orgs" / "example.json").read_text()))
        self.assertTrue(caps, "orgs/example.json names no run cap at all")

    def test_every_cap_in_the_overlay_is_a_positive_whole_number(self):
        caps = self.caps_in(json.loads((PAPERCLIP / "orgs" / "example.json").read_text()))
        for where, value in caps:
            with self.subTest(cap=where):
                self.assertNotIn(value, (0, None, ""), f"{where} disables the breaker")
                self.assertNotIsInstance(value, bool)
                self.assertIsInstance(value, int, f"{where} is {value!r}")
                self.assertGreater(value, 0)

    def test_the_library_accepts_both_files(self):
        """`validate_run_caps` is the rule the scripts enforce at apply time."""
        for rel in ("company.json", "orgs/example.json"):
            with self.subTest(path=rel):
                lib.validate_run_caps(lib.load_config(PAPERCLIP / rel))


class ConfigLoadsTests(unittest.TestCase):
    def test_the_shipped_config_loads(self):
        cfg = lib.load_config(PAPERCLIP / "company.json")
        self.assertEqual([a["key"] for a in cfg["agents"]], ["chief-of-staff", "lead"])

    def test_the_overlay_extends_the_shipped_config(self):
        cfg = lib.load_config(PAPERCLIP / "orgs" / "example.json")
        self.assertNotIn("extends", cfg)
        self.assertEqual([a["key"] for a in cfg["agents"]], ["chief-of-staff", "lead"])


class ScrubTests(unittest.TestCase):
    """The template is public. Nothing here may carry an identifier or a name
    from the practice it was generalised from."""

    def test_no_file_carries_a_uuid(self):
        for path in scanned_files():
            with self.subTest(path=path.relative_to(REPO)):
                found = UUID.search(path.read_text())
                self.assertIsNone(found, f"{path.name} carries an identifier: {found and found.group()}")

    def test_no_file_carries_a_banned_name(self):
        for path in scanned_files():
            with self.subTest(path=path.relative_to(REPO)):
                found = BANNED_WORD.search(path.read_text())
                self.assertIsNone(found, f"{path.name} names {found and found.group()!r}")

    def test_no_file_carries_a_banned_substring(self):
        for path in scanned_files():
            text = path.read_text().lower()
            for banned in BANNED_SUBSTRINGS:
                with self.subTest(path=path.relative_to(REPO), banned=banned):
                    self.assertNotIn(banned, text)


class VoiceBlockTests(unittest.TestCase):
    """A voice block shapes tone and grants nothing. The disclaimer says so in
    the file itself, where the agent reads it, not only in the README."""

    def test_each_example_file_ends_with_a_voice_block(self):
        for rel in VOICE_FILES:
            with self.subTest(path=rel):
                text = (PAPERCLIP / rel).read_text()
                self.assertIn("\n## Voice\n", text)
                after = text.split("\n## Voice\n")[-1]
                self.assertNotIn("\n## ", after, f"{rel} has a heading after ## Voice")

    def test_each_voice_block_carries_the_disclaimer_verbatim(self):
        for rel in VOICE_FILES:
            with self.subTest(path=rel):
                block = (PAPERCLIP / rel).read_text().split("\n## Voice\n")[-1]
                self.assertIn(DISCLAIMER, squash(block))


class WordBudgetTests(unittest.TestCase):
    """An instructions file is loaded on every run of that agent, so it stays
    under 500 words. A `> FILL:` block does not count: the setup pass deletes
    it, and a file that only fits while unfilled is not a file that fits."""

    def body_words(self, rel):
        lines = [ln for ln in (PAPERCLIP / rel).read_text().splitlines()
                 if not ln.lstrip().startswith(">")]
        return len(" ".join(lines).split())

    def test_each_example_instructions_file_is_under_500_words(self):
        for rel in ("agents/chief-of-staff/AGENTS.md", "agents/lead/AGENTS.md"):
            with self.subTest(path=rel):
                self.assertLess(self.body_words(rel), 500)


class SubagentSpecTests(unittest.TestCase):
    def test_each_spec_opens_with_the_same_frontmatter_keys(self):
        for rel in ("subagents/builder.md", "subagents/reviewer.md"):
            with self.subTest(path=rel):
                text = (PAPERCLIP / rel).read_text()
                self.assertTrue(text.startswith("---\n"))
                front = text.split("---\n")[1]
                for key in ("name:", "lead:", "roles:", "effort:", "models:"):
                    self.assertIn(key, front, f"{rel} frontmatter is missing {key}")


class ReadmeTests(unittest.TestCase):
    """The README is where a person learns the three traps before they hit
    one: the gate between a scope and a build, the self-policed idea caps that
    keep the heartbeat off, and the cap of `0` that enforces nothing."""

    def setUp(self):
        self.text = squash((PAPERCLIP / "README.md").read_text().lower())

    def test_it_states_the_gate_between_a_scope_and_a_build(self):
        self.assertIn("gate", self.text)
        self.assertIn("scope", self.text)

    def test_it_says_the_source_of_truth_is_here_and_the_server_holds_a_copy(self):
        self.assertIn("source of truth", self.text)
        self.assertIn("copy", self.text)

    def test_it_says_a_cap_of_zero_disables_the_breaker(self):
        self.assertIn("a cap of `0`", self.text)
        self.assertIn("breaker", self.text)

    def test_it_ties_the_self_policed_idea_caps_to_the_heartbeat_staying_off(self):
        self.assertIn("self-policed", self.text)
        self.assertIn("heartbeat", self.text)


class IdeaLedgerTests(unittest.TestCase):
    def setUp(self):
        self.text = squash((PAPERCLIP / "ideas.md").read_text().lower())

    def test_the_five_stages_are_named(self):
        for stage in ("seed", "developing", "ready", "proposed", "dropped"):
            with self.subTest(stage=stage):
                self.assertIn(stage, self.text)

    def test_the_three_caps_are_stated(self):
        self.assertIn("one move a run", self.text)
        self.assertIn("three", self.text)
        self.assertIn("one proposal", self.text)

    def test_the_ledger_is_untracked_and_a_proposal_is_one_backlog_issue(self):
        self.assertIn(".paperclip/", self.text)
        self.assertIn("backlog", self.text)


class SetupPromptTests(unittest.TestCase):
    """Stage 2 points at the scaffold, and the prompt carries the three
    cautions a person cannot recover from on their own."""

    def setUp(self):
        self.text = squash((REPO / "prompts" / "setup-paperclip.md").read_text().lower())

    def test_stage_two_points_at_the_scaffold(self):
        self.assertIn("fill", self.text)
        self.assertIn("paperclip/company.json", self.text)

    def test_the_heartbeat_caution_names_the_self_policed_caps(self):
        self.assertIn("self-policed", self.text)

    def test_the_zero_cap_caution_is_there(self):
        self.assertIn("breaker", self.text)

    def test_the_cap_pause_caution_says_a_person_resumes_it(self):
        self.assertIn("does not resume", self.text)


if __name__ == "__main__":
    unittest.main()
