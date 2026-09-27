"""The public scrub: nothing in this repository may carry a real identifier.

Run with:

    uv run --quiet --with pytest python -m pytest scripts/tests -q

This template is public, and so is any workbench cloned from it that the owner
publishes. Every markdown and JSON file in the tree is read here, not a
fixture, and each one is checked for the four shapes that leak: a UUID, a
Discord snowflake, an absolute home directory path, and a Discord webhook URL.
A fifth check reads `scrub-words.txt`, the per-workbench word list, and fails
on any word in it.

Each pattern is tested against a sample of its own as well, so a check that
stopped matching cannot pass by matching nothing.
"""

import re
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent

# A file in this tree is markdown or JSON. Anything else is not scanned.
SCANNED_SUFFIXES = {".md", ".json"}

# Directories that hold no authored file. `.git` holds every past revision, and
# the rest are build or test caches, so a hit in one of them is not a leak a
# person can fix by editing a file.
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "node_modules", ".venv"}

UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                  r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

# A Discord snowflake: 17 to 20 digits, and every ID Discord has issued since
# 2015 starts with a 1. A guild, channel, application, or user ID is one.
SNOWFLAKE = re.compile(r"\b1\d{16,19}\b")

# An absolute home directory path names the person who owns the machine, so it
# is an identifier. The name part takes no angle bracket, which leaves a
# placeholder such as `/Users/<name>` passing.
HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")

# A Discord webhook URL is a bearer credential. It never belongs in a tracked
# file, whatever else the scrub allows.
BANNED_SUBSTRINGS = ["discord.com/api/webhooks"]

# A word list each workbench fills in for itself: the agent names, the business
# name, and the repository owner that must not reach a public repository. The
# template ships it empty on purpose, because writing those words here would
# put them in this repository, which is the leak the check exists to stop. One
# word per line, `#` for a comment. Each is matched on a word boundary, so an
# ordinary word that contains one, such as "usage", passes.
SCRUB_WORDS_FILE = Path(__file__).resolve().parent / "scrub-words.txt"


def scrub_words():
    if not SCRUB_WORDS_FILE.is_file():
        return []
    return [line.strip() for line in SCRUB_WORDS_FILE.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def scanned_files():
    """Every markdown and JSON file in the tree, outside the skipped directories."""
    found = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if SKIP_DIRS & set(path.relative_to(REPO).parts[:-1]):
            continue
        found.append(path)
    return sorted(found)


class ScanTests(unittest.TestCase):
    """A scan that found no file would pass every check below for the wrong
    reason, so the file list is asserted first."""

    def test_the_scan_finds_the_files_a_reader_would_expect(self):
        names = {str(p.relative_to(REPO)) for p in scanned_files()}
        for expected in ("AGENTS.md", "README.md", "bootstrap.settings.json",
                         "central-context/AGENTS.md", "scripts/README.md"):
            with self.subTest(path=expected):
                self.assertIn(expected, names)

    def test_the_scan_skips_the_git_directory_and_the_caches(self):
        for path in scanned_files():
            parts = set(path.relative_to(REPO).parts)
            with self.subTest(path=path.relative_to(REPO)):
                self.assertEqual(SKIP_DIRS & parts, set())


class PatternTests(unittest.TestCase):
    """Each pattern, against text that must match and text that must not. A
    check that silently stopped matching would pass the scan below."""

    def test_the_uuid_pattern_matches_a_uuid_and_nothing_ordinary(self):
        self.assertTrue(UUID.search("companyId: 4d4bc69c-3682-4724-9bb7-cf2369c1b4fd"))
        self.assertFalse(UUID.search("<company-uuid>"))
        self.assertFalse(UUID.search("2026-09-27 is a date"))

    def test_the_snowflake_pattern_matches_an_id_and_nothing_ordinary(self):
        self.assertTrue(SNOWFLAKE.search("guild 1234567890123456789"))
        self.assertFalse(SNOWFLAKE.search("<guild id>"))
        self.assertFalse(SNOWFLAKE.search("port 3100, version 2026.916.1"))

    def test_the_home_path_pattern_matches_a_real_path_and_not_a_placeholder(self):
        self.assertTrue(HOME_PATH.search("/Users/someone/Projects/Code"))
        self.assertTrue(HOME_PATH.search("/home/someone/projects"))
        self.assertFalse(HOME_PATH.search("/Users/<name>/Projects"))
        self.assertFalse(HOME_PATH.search("/home/<name>"))
        self.assertFalse(HOME_PATH.search("~/Library/LaunchAgents"))

    def test_the_word_reader_handles_comments_and_blank_lines(self):
        self.assertEqual(scrub_words(), [])


class ScrubTests(unittest.TestCase):
    """The scan itself. One subtest per file, so a failure names the file."""

    def test_no_file_carries_a_uuid(self):
        for path in scanned_files():
            with self.subTest(path=path.relative_to(REPO)):
                found = UUID.search(path.read_text())
                self.assertIsNone(found, f"carries an identifier: {found and found.group()}")

    def test_no_file_carries_a_discord_snowflake(self):
        for path in scanned_files():
            with self.subTest(path=path.relative_to(REPO)):
                found = SNOWFLAKE.search(path.read_text())
                self.assertIsNone(found, f"carries a Discord ID: {found and found.group()}")

    def test_no_file_carries_an_absolute_home_directory_path(self):
        """A home path names the owner of the machine, and it also makes the
        file wrong on anyone else's."""
        for path in scanned_files():
            with self.subTest(path=path.relative_to(REPO)):
                found = HOME_PATH.search(path.read_text())
                self.assertIsNone(found, f"carries a home path: {found and found.group()}")

    def test_no_file_carries_a_scrub_word(self):
        words = scrub_words()
        if not words:
            self.skipTest("scrub-words.txt is empty; a derived workbench fills it in")
        pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b",
                             re.IGNORECASE)
        for path in scanned_files():
            with self.subTest(path=path.relative_to(REPO)):
                found = pattern.search(path.read_text())
                self.assertIsNone(found, f"names {found and found.group()!r}")

    def test_no_file_carries_a_banned_substring(self):
        for path in scanned_files():
            text = path.read_text().lower()
            for banned in BANNED_SUBSTRINGS:
                with self.subTest(path=path.relative_to(REPO), banned=banned):
                    self.assertNotIn(banned, text)

    def test_the_scrub_word_list_is_readable_and_ships_empty(self):
        """The reader must handle comments, blanks, and the shipped empty file.
        A template that shipped words would be the leak it checks for."""
        self.assertTrue(SCRUB_WORDS_FILE.is_file(), "scrub-words.txt is missing")
        self.assertEqual(scrub_words(), [])
        self.assertIn("#", SCRUB_WORDS_FILE.read_text())


if __name__ == "__main__":
    unittest.main()
