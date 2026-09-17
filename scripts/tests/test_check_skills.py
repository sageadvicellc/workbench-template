"""Tests for scripts/check-skills.py.

The behaviour under test is described in the script's own module docstring
and in scripts/README.md. This template ships no SPEC.md; write one when a
change here needs acceptance criteria of its own.

Each test method names the criterion number it covers in its docstring.
Standard library only: unittest, tempfile, pathlib, ast, subprocess, sysconfig,
importlib. Run with:

    python3 -m unittest discover -s scripts/tests

check-skills.py is never edited by this file. A failing test is a finding
about the script, not a reason to change the assertion.
"""

import ast
import contextlib
import importlib.util
import io
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check-skills.py"
WORKBENCH_ROOT = SCRIPT_PATH.parent.parent

_spec = importlib.util.spec_from_file_location("check_skills", SCRIPT_PATH)
check_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_skills)

SKILLS = check_skills.SKILLS_DIR


def skill_md(name, description="does a thing"):
    lines = ["---", f"name: {name}"]
    if description is not None:
        lines.append(f"description: {description}")
    lines.append("---")
    lines.append("Body.")
    return "\n".join(lines) + "\n"


class CheckSkillsTest(unittest.TestCase):
    def _root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def _write(self, root, rel, text):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _skill(self, root, directory, text):
        return self._write(root, f"{SKILLS}/{directory}/SKILL.md", text)

    def _exempt(self, name="an-installed-skill"):
        """Mark one directory exempt for this test, restoring the real set after.

        THIRD_PARTY_SKILLS is empty in a fresh workbench and populated in one
        that has installed third-party skills. A test that indexes into the
        live set therefore errors in the first tree and passes in the second,
        which makes the suite depend on which clone it runs in. Supplying the
        exemption keeps the behaviour under test the same everywhere."""
        original = set(check_skills.THIRD_PARTY_SKILLS)
        check_skills.THIRD_PARTY_SKILLS.add(name)

        def restore():
            check_skills.THIRD_PARTY_SKILLS.clear()
            check_skills.THIRD_PARTY_SKILLS.update(original)

        self.addCleanup(restore)
        return name

    def _quiet_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check_skills.main(argv)
        return code, buf.getvalue()

    def _base(self):
        """A root with an empty wiki/skills/ directory and nothing else."""
        root = self._root()
        (root / SKILLS).mkdir(parents=True)
        return root

    # -- 1: a nested SKILL.md is a failure, named, at any depth --------------

    def test_nested_skill_file_one_level_deep_is_a_failure(self):
        """Criterion 1: <dir>/nested/SKILL.md is reported, path named."""
        root = self._base()
        self._skill(root, "alpha", skill_md("alpha"))
        self._write(root, f"{SKILLS}/alpha/nested/SKILL.md", skill_md("alpha"))
        failures = check_skills.run(root)
        matches = [f for f in failures if f.startswith(f"{SKILLS}/alpha/nested/SKILL.md")]
        self.assertEqual(len(matches), 1)
        self.assertIn("not discovered", matches[0])

    def test_nested_skill_file_several_levels_deep_is_also_a_failure(self):
        """Criterion 1: depth does not matter, <dir>/a/b/SKILL.md fails too."""
        root = self._base()
        self._skill(root, "alpha", skill_md("alpha"))
        self._write(root, f"{SKILLS}/alpha/nested/SKILL.md", skill_md("alpha"))
        self._write(root, f"{SKILLS}/alpha/a/b/SKILL.md", skill_md("alpha"))
        failures = check_skills.run(root)
        self.assertTrue(any(f.startswith(f"{SKILLS}/alpha/nested/SKILL.md") for f in failures))
        self.assertTrue(any(f.startswith(f"{SKILLS}/alpha/a/b/SKILL.md") for f in failures))

    # -- 2: exactly one failure for a nested file, its frontmatter unread -----

    def test_nested_skill_with_broken_frontmatter_produces_only_the_nesting_failure(self):
        """Criterion 2: a nested file's frontmatter is never read, whatever it says."""
        root = self._base()
        self._skill(root, "alpha", skill_md("alpha"))
        self._write(root, f"{SKILLS}/alpha/nested/SKILL.md", "not frontmatter at all, no ---\n")
        failures = check_skills.run(root)
        related = [f for f in failures if "alpha/nested/SKILL.md" in f]
        self.assertEqual(len(related), 1)
        self.assertIn("not discovered", related[0])

    def test_valid_skill_next_to_a_nested_one_still_gets_checked(self):
        """Criterion 2 and 5: the directory's own SKILL.md is still checked
        when a nested one also exists; the nested failure does not replace it."""
        root = self._base()
        # Missing description on purpose, to prove the top-level file is
        # actually read and not skipped just because a nested file exists.
        self._skill(root, "gamma", skill_md("gamma", description=None))
        self._write(root, f"{SKILLS}/gamma/nested/SKILL.md", skill_md("gamma"))
        failures = check_skills.run(root)
        self.assertTrue(any(f.startswith(f"{SKILLS}/gamma/nested/SKILL.md") for f in failures))
        self.assertTrue(any(
            f.startswith(f"{SKILLS}/gamma/SKILL.md") and "no description" in f
            for f in failures
        ))
        self.assertFalse(any("no SKILL.md" in f and "gamma" in f for f in failures))

    def test_directory_with_only_a_nested_skill_file_fails_once_not_twice(self):
        """Criterion 2: no own SKILL.md plus a nested one is the nesting
        failure only, never also a 'no SKILL.md' failure."""
        root = self._base()
        self._write(root, f"{SKILLS}/delta/deep/SKILL.md", skill_md("delta"))
        failures = check_skills.run(root)
        delta_failures = [f for f in failures if "delta" in f]
        self.assertEqual(len(delta_failures), 1)
        self.assertIn("not discovered", delta_failures[0])

    # -- 2: a skill directory with nothing in it, dot dirs exempt ------------

    def test_empty_skill_directory_is_one_failure_naming_it(self):
        """Criterion 2: a directory with no skill file of its own fails."""
        root = self._base()
        (root / SKILLS / "epsilon").mkdir()
        failures = check_skills.run(root)
        matches = [f for f in failures if f.startswith(f"{SKILLS}/epsilon")]
        self.assertEqual(len(matches), 1)
        self.assertIn("no SKILL.md", matches[0])

    def test_dot_directory_under_skills_is_never_reported(self):
        """Criterion 2: a dot directory holds no skill file and stays silent."""
        root = self._base()
        (root / SKILLS / ".obsidian").mkdir()
        (root / SKILLS / ".obsidian" / "graph.json").write_text("{}")
        failures = check_skills.run(root)
        self.assertFalse(any(".obsidian" in f for f in failures))

    # -- 3, 4, 5: the name check and its one exemption -----------------------

    def test_skill_name_mismatched_with_its_directory_fails(self):
        """Criterion 3: no allowlist protects a mismatched name by default."""
        root = self._base()
        self._skill(root, "my-new-skill", skill_md("typoed-nmae"))
        failures = check_skills.run(root)
        self.assertTrue(any(
            f.startswith(f"{SKILLS}/my-new-skill/SKILL.md") and "does not match directory" in f
            for f in failures
        ))

    def test_name_check_applies_to_every_skill_not_in_third_party_skills(self):
        """Criterion 3, written as behaviour rather than as a source-shape
        check: every directory outside THIRD_PARTY_SKILLS gets the name check,
        whatever the limiter is named."""
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("FIRST_PARTY_SKILLS", source)
        exempt = set(check_skills.THIRD_PARTY_SKILLS)
        candidates = ["my-new-skill", "wiki-query", "another-skill", "wiki-lint"]
        root = self._base()
        for name in candidates:
            self.assertNotIn(name, exempt, "fixture name collides with a real exemption")
            self._skill(root, name, skill_md("mismatched-name"))
        failures = check_skills.run(root)
        mismatched = {f.split("/")[2] for f in failures if "does not match directory" in f}
        self.assertEqual(mismatched, set(candidates))

    def test_directory_in_third_party_skills_is_exempt_from_the_name_check(self):
        """Criterion 3: the same mismatch that fails for an ordinary
        directory passes once the directory is one of the exempt ones."""
        exempt = self._exempt()
        root = self._base()
        self._skill(root, exempt, skill_md("some-other-name"))
        failures = check_skills.run(root)
        self.assertFalse(any(
            f.startswith(f"{SKILLS}/{exempt}/SKILL.md") and "does not match directory" in f
            for f in failures
        ))

    def test_exempt_skill_with_no_description_still_fails(self):
        """Criterion 5: the exemption suppresses only the name-match check."""
        exempt = self._exempt()
        root = self._base()
        self._skill(root, exempt, skill_md("some-other-name", description=None))
        failures = check_skills.run(root)
        self.assertTrue(any(
            f.startswith(f"{SKILLS}/{exempt}/SKILL.md") and "no description" in f
            for f in failures
        ))
        self.assertFalse(any("does not match directory" in f for f in failures))

    def test_exempt_skill_with_uppercase_name_still_fails_the_shape_check(self):
        """Criterion 4: exemption does not touch the lowercase-hyphen shape
        check, even on an exempt directory."""
        exempt = self._exempt()
        root = self._base()
        self._skill(root, exempt, skill_md("Some-Other-Name"))
        failures = check_skills.run(root)
        self.assertTrue(any(
            f.startswith(f"{SKILLS}/{exempt}/SKILL.md") and "not lowercase-hyphen" in f
            for f in failures
        ))

    def test_ordinary_skill_with_uppercase_name_fails_the_shape_check(self):
        """Criterion 4: a name with a capital letter fails outside the
        exemption too."""
        root = self._base()
        self._skill(root, "zeta", skill_md("lowercase-Name"))
        failures = check_skills.run(root)
        self.assertTrue(any(
            f.startswith(f"{SKILLS}/zeta/SKILL.md") and "not lowercase-hyphen" in f
            for f in failures
        ))

    def test_skill_name_over_64_characters_fails(self):
        """Criterion 4: name is 1 to 64 characters. A 65-character name fails."""
        root = self._base()
        long_name = "a" * 65
        self._skill(root, long_name, f"---\nname: {long_name}\ndescription: fine.\n---\n")
        failures = check_skills.run(root)
        self.assertTrue(
            any("over the 64" in f for f in failures),
            f"expected a length failure, got {failures}")

    def test_skill_name_of_exactly_64_characters_passes(self):
        """Criterion 4: 64 is allowed, so the boundary must not fail."""
        root = self._base()
        name = "a" * 64
        self._skill(root, name, f"---\nname: {name}\ndescription: fine.\n---\n")
        self.assertEqual(check_skills.run(root), [])

    def test_length_rule_runs_on_exempt_skills_too(self):
        """An exemption covers the name-matches-directory rule and nothing else."""
        exempt = self._exempt()
        root = self._base()
        self._skill(root, exempt, f"---\nname: {'b' * 65}\ndescription: fine.\n---\n")
        failures = check_skills.run(root)
        self.assertTrue(
            any("over the 64" in f for f in failures),
            f"exempt skill should still fail the length rule, got {failures}")

    def test_the_exemption_is_keyed_on_third_party_skills_membership(self):
        """Criterion 3, strengthened: one fixture run both ways, with
        membership as the only thing that changes."""
        name = "an-installed-skill"
        root = self._base()
        self._skill(root, name, skill_md("some-other-name"))
        before = check_skills.run(root)
        self.assertTrue(any(f"{SKILLS}/{name}/SKILL.md" in f and "does not match directory" in f
                            for f in before),
                        "the mismatch must fail while the directory is not exempt")
        self._exempt(name)
        after = check_skills.run(root)
        self.assertFalse(any(f"{SKILLS}/{name}/SKILL.md" in f and "does not match directory" in f
                             for f in after),
                         "the exemption must suppress exactly that failure")

    def test_exempt_helper_restores_the_set(self):
        """_exempt mutates a module global; without the restore it leaks into
        every later test, invisibly."""
        original = set(check_skills.THIRD_PARTY_SKILLS)
        class Inner(unittest.TestCase):
            def runTest(inner):
                inner.addCleanup(lambda: None)
                CheckSkillsTest._exempt(inner, "leaked-name")
                self.assertIn("leaked-name", check_skills.THIRD_PARTY_SKILLS)
        Inner().run(unittest.TestResult())
        self.assertEqual(set(check_skills.THIRD_PARTY_SKILLS), original,
                         "the set was not restored after the test finished")

    # -- 6: the skills root itself --------------------------------------------

    def test_missing_skills_directory_is_named_as_a_failure(self):
        """Criterion 6: an empty tree used to report '0 failure(s)' and exit 0.
        A missing wiki/skills/ is now one named failure."""
        root = self._root()
        self.assertEqual(check_skills.run(root),
                         [f"{SKILLS}: no such directory at the checked root"])

    def test_a_flat_skills_directory_is_not_the_skills_root(self):
        """Criterion 6: skills/ at the root is not where skills live now, so a
        tree holding only that one is reported, not read."""
        root = self._root()
        self._write(root, "skills/alpha/SKILL.md", skill_md("alpha"))
        self.assertEqual(check_skills.run(root),
                         [f"{SKILLS}: no such directory at the checked root"])

    def test_a_skill_directly_under_the_skills_root_passes(self):
        """Criterion 6: the shape the template ships, wiki/skills/<name>/SKILL.md."""
        root = self._base()
        self._skill(root, "wiki-query", skill_md("wiki-query"))
        self.assertEqual(check_skills.run(root), [])

    # -- the exit code formula, and the zero-failure message -------------------

    def test_clean_tree_prints_zero_failures_and_exits_zero(self):
        root = self._base()
        code, out = self._quiet_main(["check-skills.py", str(root)])
        self.assertEqual(code, 0)
        self.assertIn("0 failure(s)", out)

    def test_exit_code_is_the_failure_count(self):
        root = self._base()
        (root / SKILLS / "empty-one").mkdir()
        (root / SKILLS / "empty-two").mkdir()
        code, _ = self._quiet_main(["check-skills.py", str(root)])
        self.assertEqual(code, 2)

    def test_exit_code_caps_at_125_past_the_limit(self):
        root = self._base()
        for i in range(130):
            (root / SKILLS / f"empty-{i}").mkdir()
        code, _ = self._quiet_main(["check-skills.py", str(root)])
        self.assertEqual(code, 125)

    # -- every failure line starts with a path relative to the root -----------

    def test_failure_lines_start_with_the_relative_path_across_several_failure_kinds(self):
        """The offending path leads the line, not a prefix like the absolute
        temp directory or a generic label. Checked across four failure kinds
        at once, not just the easiest one to trigger."""
        root = self._base()
        (root / SKILLS / "epsilon").mkdir()                                      # no SKILL.md
        self._skill(root, "alpha", skill_md("alpha"))
        self._write(root, f"{SKILLS}/alpha/nested/SKILL.md", skill_md("alpha"))  # nested
        self._skill(root, "zeta", skill_md("mismatched"))                        # name mismatch
        self._write(root, f"{SKILLS}/binary/SKILL.md", "")
        (root / SKILLS / "binary" / "SKILL.md").write_bytes(b"\x80\x81 not utf8")
        failures = check_skills.run(root)
        expected_prefixes = (
            f"{SKILLS}/epsilon",
            f"{SKILLS}/alpha/nested/SKILL.md",
            f"{SKILLS}/zeta/SKILL.md",
            f"{SKILLS}/binary/SKILL.md",
        )
        self.assertGreaterEqual(len(failures), len(expected_prefixes))
        for f in failures:
            self.assertTrue(f.startswith(expected_prefixes), f)
            self.assertNotIn(str(root), f)
        for prefix in expected_prefixes:
            self.assertTrue(any(f.startswith(prefix) for f in failures), prefix)

    # -- the command line ------------------------------------------------------

    def test_default_invocation_from_elsewhere_still_checks_workbench_root(self):
        """No arguments, run with a different cwd, still checks the workbench
        root because it resolves from the script's own path."""
        elsewhere = self._root()
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=str(elsewhere),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 failure(s)", result.stdout)

    # -- standard library only -------------------------------------------------

    def test_script_imports_nothing_outside_the_standard_library(self):
        """Every top-level import resolves inside the stdlib."""
        # Both sides resolved: a Homebrew Python reports the stdlib through a
        # symlinked prefix while find_spec() returns the real Cellar path, and
        # is_relative_to() compares lexically.
        stdlib_dir = Path(sysconfig.get_paths()["stdlib"]).resolve()
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        self.assertTrue(names)
        for name in names:
            spec = importlib.util.find_spec(name)
            self.assertIsNotNone(spec, f"{name} is not importable at all")
            origin = spec.origin
            is_builtin = origin in (None, "built-in", "frozen")
            is_stdlib = bool(origin) \
                and Path(origin).resolve().is_relative_to(stdlib_dir) \
                and "site-packages" not in origin
            self.assertTrue(is_builtin or is_stdlib, f"{name} is not standard library")

    # -- run(root) is the seam a test builds a fixture tree against -----------

    def test_run_accepts_a_plain_string_path_as_well_as_a_path_object(self):
        root = self._base()
        (root / SKILLS / "epsilon").mkdir()
        self.assertEqual(check_skills.run(root), check_skills.run(str(root)))

    # -- the real tree, checked, reports nothing ------------------------------

    def test_real_workbench_root_has_no_failures(self):
        """The regression check on the actual tree."""
        self.assertEqual(check_skills.run(WORKBENCH_ROOT), [])

    # -- the docstring and scripts/README.md describe the check as it runs ----

    def test_docstring_names_the_exemption_set_not_a_first_party_allowlist(self):
        """The module docstring describes THIRD_PARTY_SKILLS, and neither it
        nor scripts/README.md claims the name check is limited to a list of
        skills the practice wrote."""
        docstring = check_skills.__doc__ or ""
        self.assertIn("THIRD_PARTY_SKILLS", docstring)
        readme = (WORKBENCH_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
        for text in (docstring, readme):
            self.assertNotIn("FIRST_PARTY_SKILLS", text)

    def test_the_script_and_its_documentation_carry_no_role_rules(self):
        """The template ships no roles. A rule about agents/ or a model
        registry left behind here would describe a check nothing runs."""
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        readme = (WORKBENCH_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
        for text in (source, readme):
            self.assertNotIn("model-registry", text)
            self.assertNotIn("agents/", text)

    # -- a SKILL.md that is a directory or a dangling symlink ----------------

    def test_skill_md_that_is_a_directory_is_reported_as_not_a_readable_file(self):
        """A SKILL.md that is itself a directory used to crash with
        IsADirectoryError. It is now a distinct, named failure."""
        root = self._base()
        (root / SKILLS / "foo" / "SKILL.md").mkdir(parents=True)
        failures = check_skills.run(root)
        self.assertIn(f"{SKILLS}/foo: SKILL.md is not a readable file", failures)

    def test_skill_md_that_is_a_dangling_symlink_is_reported_as_not_a_readable_file(self):
        """A dangling symlink named SKILL.md used to crash with
        FileNotFoundError. Same message as the directory case."""
        root = self._base()
        target = root / SKILLS / "bar"
        target.mkdir(parents=True)
        try:
            (target / "SKILL.md").symlink_to(target / "does-not-exist.md")
        except OSError as exc:
            self.skipTest(f"symlinks not supported here: {exc}")
        failures = check_skills.run(root)
        self.assertIn(f"{SKILLS}/bar: SKILL.md is not a readable file", failures)

    def test_absent_skill_md_keeps_its_own_distinct_message(self):
        """An absent file and an unreadable one are deliberately different
        messages, never conflated into one."""
        root = self._base()
        (root / SKILLS / "baz").mkdir()
        failures = check_skills.run(root)
        self.assertIn(f"{SKILLS}/baz: no SKILL.md", failures)
        self.assertNotIn(f"{SKILLS}/baz: SKILL.md is not a readable file", failures)

    # -- no trailing newline after the closing fence -------------------------

    def test_frontmatter_with_no_trailing_newline_after_the_closing_fence_parses(self):
        """A file whose last byte is the closing fence's final '-' is valid.
        It used to be reported as having no frontmatter at all."""
        root = self._base()
        self._skill(root, "nonl", "---\nname: nonl\ndescription: does a thing\n---")
        self.assertEqual(check_skills.run(root), [])

    # -- a byte order mark before the opening fence --------------------------

    def test_utf8_bom_before_the_opening_fence_gets_its_own_message(self):
        """A byte order mark is named specifically, not lumped into the
        generic 'no frontmatter' failure."""
        root = self._base()
        self._skill(root, "bombed", "﻿---\nname: bombed\ndescription: does a thing\n---\n")
        failures = check_skills.run(root)
        self.assertIn(
            f"{SKILLS}/bombed/SKILL.md: starts with a byte order mark, "
            f"so --- is not the first thing in it",
            failures,
        )
        self.assertFalse(any("no frontmatter" in f for f in failures))

    def test_a_file_with_no_frontmatter_at_all_is_reported(self):
        root = self._base()
        self._skill(root, "plain", "# Just a heading\n\nBody.\n")
        failures = check_skills.run(root)
        self.assertIn(
            f"{SKILLS}/plain/SKILL.md: no frontmatter, or --- is not the first line",
            failures,
        )

    # -- text that is not UTF-8, and a file that cannot be read --------------

    def test_file_that_is_not_utf8_reports_that_specifically(self):
        """Invalid UTF-8 bytes get their own message, not a generic parse
        failure."""
        root = self._base()
        (root / SKILLS / "binary").mkdir()
        (root / SKILLS / "binary" / "SKILL.md").write_bytes(b"\x80\x81\x82 not utf8 at all")
        failures = check_skills.run(root)
        self.assertIn(f"{SKILLS}/binary/SKILL.md: is not UTF-8 text", failures)

    def test_unreadable_skill_file_is_one_failure_not_a_traceback(self):
        """A self-referential symlink is unreadable in every POSIX
        environment, root included, unlike a chmod'd file, which root can
        still read, so this is the portable way to force it without depending
        on the runner's privilege level. Skipped where symlinks are not
        supported at all."""
        root = self._base()
        (root / SKILLS / "loop").mkdir()
        loop = root / SKILLS / "loop" / "SKILL.md"
        try:
            loop.symlink_to(loop)
        except OSError as exc:
            self.skipTest(f"symlinks not supported here: {exc}")
        failures = check_skills.run(root)
        matches = [f for f in failures if f.startswith(f"{SKILLS}/loop")]
        self.assertEqual(len(matches), 1)
        self.assertIn("is not a readable file", matches[0])


if __name__ == "__main__":
    unittest.main()
