"""Tests for the CI workflows under .github/workflows/.

This repository is public, so a pull request from a fork runs these
workflows. The tests hold every workflow to the fork-safe shape: it runs on
`pull_request` and `workflow_dispatch`, never on `pull_request_target`, reads
no secret, grants `contents: read` and nothing else at the top level and in
every job, pins every action to a full commit SHA, and checks out without
persisting the token.

Standard library only, so the file reads the YAML as text, line by line. It
understands the block style these workflows use and nothing more. Run with:

    python3 -m unittest discover -s scripts/tests
"""

import re
import unittest
from pathlib import Path

WORKBENCH_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = WORKBENCH_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"


def _workflow_files():
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def _code_lines(text):
    """Each line with a trailing comment removed. A `#` inside a quoted
    string is not a comment, but no workflow here quotes one."""
    return [re.sub(r"\s+#.*$", "", line) if not line.lstrip().startswith("#") else ""
            for line in text.splitlines()]


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _block(lines, start):
    """The lines indented under lines[start], without blank lines."""
    base = _indent(lines[start])
    out = []
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if _indent(line) <= base:
            break
        out.append(line)
    return out


def _mapping(lines, key, indent):
    """The block under the first `key:` at exactly this indent, or None."""
    for i, line in enumerate(lines):
        if _indent(line) == indent and line.strip() == f"{key}:":
            return _block(lines, i)
    return None


def _entries(block):
    """The `name: value` pairs at the block's own top indent."""
    if not block:
        return {}
    top = min(_indent(line) for line in block)
    pairs = {}
    for line in block:
        if _indent(line) == top and ":" in line:
            k, _, v = line.strip().partition(":")
            pairs[k.strip()] = v.strip()
    return pairs


def _jobs(lines):
    """Each job id with the lines indented under it."""
    jobs_block_start = next(i for i, line in enumerate(lines)
                            if _indent(line) == 0 and line.strip() == "jobs:")
    body = lines[jobs_block_start + 1:]
    jobs = {}
    for i, line in enumerate(body):
        if _indent(line) == 0 and line.strip():
            break
        if _indent(line) == 2 and line.rstrip().endswith(":"):
            jobs[line.strip()[:-1]] = _block(body, i)
    return jobs


class CiWorkflowTests(unittest.TestCase):

    def setUp(self):
        self.assertTrue(CI.is_file(), f"{CI.relative_to(WORKBENCH_ROOT)} is missing")
        self.lines = _code_lines(CI.read_text(encoding="utf-8"))

    def test_triggers_are_pull_request_and_workflow_dispatch_only(self):
        on = _entries(_mapping(self.lines, "on", 0))
        self.assertEqual(set(on), {"pull_request", "workflow_dispatch"})

    def test_top_level_permissions_are_contents_read_only(self):
        self.assertEqual(_entries(_mapping(self.lines, "permissions", 0)),
                         {"contents": "read"})

    def test_every_job_declares_contents_read_only(self):
        jobs = _jobs(self.lines)
        self.assertTrue(jobs, "the workflow defines no job")
        for name, block in jobs.items():
            with self.subTest(job=name):
                self.assertEqual(_entries(_mapping(block, "permissions", 4)),
                                 {"contents": "read"})

    def test_checkout_does_not_persist_the_token(self):
        text = "\n".join(self.lines)
        checkouts = text.count("uses: actions/checkout@")
        self.assertGreater(checkouts, 0, "no checkout step")
        self.assertEqual(text.count("persist-credentials: false"), checkouts)

    def test_runs_the_repository_tests_and_checks(self):
        text = "\n".join(self.lines)
        for command in ("python -m unittest discover -s scripts/tests",
                        "scripts/check-harness.py",
                        "scripts/check-skills.py",
                        "scripts/check-open-items.py",
                        "scripts/sync-harness.py --check"):
            with self.subTest(command=command):
                self.assertIn(command, text)


class EveryWorkflowIsForkSafeTests(unittest.TestCase):

    def test_there_is_at_least_one_workflow(self):
        self.assertTrue(_workflow_files())

    def test_no_workflow_uses_pull_request_target(self):
        for path in _workflow_files():
            with self.subTest(workflow=path.name):
                self.assertNotIn("pull_request_target", path.read_text(encoding="utf-8"))

    def test_no_workflow_reads_a_secret(self):
        for path in _workflow_files():
            with self.subTest(workflow=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"\bsecrets\.")

    def test_no_workflow_grants_a_write_scope(self):
        for path in _workflow_files():
            text = "\n".join(_code_lines(path.read_text(encoding="utf-8")))
            with self.subTest(workflow=path.name):
                self.assertNotRegex(text, r":\s*write\b")
                self.assertNotIn("write-all", text)

    def test_every_action_is_pinned_to_a_full_commit_sha(self):
        for path in _workflow_files():
            for line in _code_lines(path.read_text(encoding="utf-8")):
                m = re.search(r"uses:\s*(\S+)", line)
                if m and not m.group(1).startswith("./"):
                    with self.subTest(workflow=path.name, uses=m.group(1)):
                        self.assertRegex(m.group(1), r"@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
