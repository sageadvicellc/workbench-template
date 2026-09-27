"""The public scrub: no tracked file but this one carries a real identifier or a
credential.

Run with:

    uv run --quiet --with pytest python -m pytest scripts/tests -q

This template is public, and so is any workbench cloned from it that the owner
publishes. Every file `git ls-files` reports is read here, not a fixture, with
one exemption: this file, which holds a sample of every shape below on purpose.
Each file is checked for the shapes that leak: a UUID, a Discord snowflake, an
absolute home directory path, a Discord webhook URL, and five credential
shapes. A further check reads `scrub-words.txt`, the per-workbench word list,
and fails on any word in it.

Tracked is the set that can reach a public remote, which is why the scan asks
git for it rather than walking the filesystem. An ignored or untracked file
cannot be published, and a nested project repository is somebody else's
problem, so neither is read. A tracked file is read whatever its suffix is: an
earlier version scanned two suffixes, and the identifier that reached this
repository sat in a `.py` file.

Each pattern is tested against a sample of its own as well, so a check that
stopped matching cannot pass by matching nothing.
"""

import base64
import datetime
import re
import subprocess
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent

# This file holds a sample of every shape the patterns catch, so scanning it
# would fail on its own samples. It is the one exemption. The tests assert that
# the list holds exactly one entry and that git tracks that entry, because an
# exemption nobody can see is a hole.
EXEMPT = (Path("scripts/tests/test_public_scrub.py"),)

UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                  r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

# A Discord snowflake is (milliseconds since 2015-01-01) << 22, so its leading
# digit tracks the date it was minted, and it takes any value. An ID minted in
# 2016 leads with a 1 or a 2, one from 2018 with a 3, one from 2021 with a 7,
# and one from 2023 or later with a 1 again, because the value passed 19 digits
# on 2022-07-22. A pattern anchored to a leading 1, as this one was, saw none
# of the 18-digit IDs minted between July 2016 and July 2022.
SNOWFLAKE = re.compile(r"\b[1-9]\d{16,19}\b")

# An absolute home directory path names the person who owns the machine, so it
# is an identifier. The name part takes no angle bracket, which leaves a
# placeholder such as `/Users/<name>` passing.
HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")

# A Discord bot token is three base64url segments joined by dots: the
# application's snowflake, a timestamp, and a signature. The first segment is
# base64 of the ID's digits, not the digits, so the snowflake pattern above
# never sees one. The shape chosen here is 23 to 28 base64url characters, then
# 6 or 7, then 27 to 40. Prose does not reach 23 characters without a space.
DISCORD_TOKEN = re.compile(
    r"\b[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,40}\b")

# A GitHub token: a five-character prefix that names its kind, then at least 36
# characters. `ghp_` is personal, `gho_` and `ghu_` are OAuth, `ghs_` is a
# server token, `ghr_` is a refresh token.
GITHUB_TOKEN = re.compile(r"\bgh[pours]_[A-Za-z0-9]{36,255}\b")

# An OpenAI-style key: `sk-`, optionally a project part, then the body. The
# word boundary keeps it off an ordinary word that ends in "sk", such as
# "risk-free".
OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")

# A Slack token. The prefix names the kind: bot, user, app, refresh, or signing.
SLACK_TOKEN = re.compile(r"\bxox[bpars]-[A-Za-z0-9-]{10,}\b")

# The first line of a private key block, in any of its forms: `RSA`, `EC`,
# `OPENSSH`, `ENCRYPTED`, or none at all.
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")

# Every credential shape, with the name a failure reports.
CREDENTIALS = (
    ("a Discord bot token", DISCORD_TOKEN),
    ("a GitHub token", GITHUB_TOKEN),
    ("an OpenAI key", OPENAI_KEY),
    ("a Slack token", SLACK_TOKEN),
    ("a private key", PRIVATE_KEY),
)

# A Discord webhook URL is a bearer credential. It never belongs in a tracked
# file, whatever else the scrub allows. Both hosts count: a webhook minted
# before the domain migration still works at the legacy host.
BANNED_SUBSTRINGS = ["discord.com/api/webhooks", "discordapp.com/api/webhooks"]

# A word list each workbench fills in for itself: the agent names, the business
# name, and the repository owner that must not reach a public repository. The
# template ships it empty on purpose, because writing those words here would
# put them in this repository, which is the leak the check exists to stop. One
# word per line, `#` for a comment. Each is matched on a word boundary, so an
# ordinary word that contains one, such as "usage", passes.
SCRUB_WORDS_FILE = Path(__file__).resolve().parent / "scrub-words.txt"

# Discord's epoch, 2015-01-01T00:00:00Z, in milliseconds.
DISCORD_EPOCH_MS = 1420070400000


def snowflake_time(value):
    """The moment a snowflake was minted. Shifting the value back by 22 bits
    recovers the millisecond count the ID was built from."""
    ms = (int(value) >> 22) + DISCORD_EPOCH_MS
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)


def snowflake_for(year, month, day):
    """A snowflake minted at midnight UTC on that date, with every low bit
    clear. Invented, like every sample here: a real ID written into this file
    would be the leak these patterns exist to catch."""
    moment = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
    ms = int(moment.timestamp() * 1000)
    return str((ms - DISCORD_EPOCH_MS) << 22)


# The samples the pattern tests match. Every one is invented. A test that
# reached for a real identifier to prove a pattern works would put that
# identifier in this repository.
SAMPLE_UUID = "0f1e2d3c-4b5a-4968-8776-65544332211a"
SAMPLE_SNOWFLAKE = "1000000000000000001"

# Three snowflakes from the years the old pattern could not see. The tests
# recover each date from the value, so the range in the SNOWFLAKE comment
# cannot drift away from the arithmetic.
SAMPLE_SNOWFLAKE_2016 = snowflake_for(2016, 7, 6)
SAMPLE_SNOWFLAKE_2018 = snowflake_for(2018, 1, 1)
SAMPLE_SNOWFLAKE_2021 = snowflake_for(2021, 1, 1)

# One invented credential per pattern, built to the shape that pattern names.
SAMPLE_DISCORD_TOKEN = (
    base64.urlsafe_b64encode(SAMPLE_SNOWFLAKE.encode()).decode().rstrip("=")
    + ".AaAaAa." + "b" * 38)
SAMPLE_GITHUB_TOKEN = "ghp_" + "A1" * 18
SAMPLE_OPENAI_KEY = "sk-proj-" + "B2" * 12
SAMPLE_SLACK_TOKEN = "xoxb-" + "1" * 13 + "-" + "c" * 24
SAMPLE_PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----"


def scrub_words():
    if not SCRUB_WORDS_FILE.is_file():
        return []
    return [line.strip() for line in SCRUB_WORDS_FILE.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def tracked_paths():
    """Every path git tracks, relative to the repository root.

    Tracked is the exact set that can reach a public remote. A git call that
    fails raises here rather than returning an empty list, because a scan that
    found nothing would pass every check below."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True,
                         capture_output=True, text=True).stdout
    return sorted(Path(rel) for rel in out.split("\0") if rel)


def file_text(rel):
    """The file's text, or None when no pattern can read it: a binary file, or
    a path that is not a regular file, such as a broken symlink."""
    path = REPO / rel
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def scanned_files():
    """Every tracked file the scan reads: tracked, less the exemption, less
    anything that is not UTF-8 text."""
    return [rel for rel in tracked_paths()
            if rel not in EXEMPT and file_text(rel) is not None]


def unreadable_files():
    """Tracked paths no pattern can read. Empty in this template."""
    return [rel for rel in tracked_paths() if file_text(rel) is None]


def banned_hits(text):
    """Every banned substring in this text. The scan and the pattern tests
    both call it, so a test cannot pass against a second implementation."""
    low = text.lower()
    return [banned for banned in BANNED_SUBSTRINGS if banned in low]


class ScanTests(unittest.TestCase):
    """A scan that found no file, or a scan narrowed back to a suffix list,
    would pass every check below for the wrong reason. The file list is
    asserted first."""

    def test_the_scan_reads_every_tracked_file_but_the_exemption(self):
        self.assertEqual(set(scanned_files()),
                         set(tracked_paths()) - set(EXEMPT) - set(unreadable_files()))

    def test_the_scan_reads_no_untracked_or_ignored_file(self):
        """An ignored cache and a nested project repository cannot be
        published, and reading them made the scan fail on files nobody here can
        edit."""
        tracked = set(tracked_paths())
        for rel in scanned_files():
            with self.subTest(path=rel):
                self.assertIn(rel, tracked)

    def test_the_scan_finds_the_files_a_reader_would_expect(self):
        names = {str(p) for p in scanned_files()}
        for expected in ("AGENTS.md", "README.md", "bootstrap.settings.json",
                         "central-context/AGENTS.md", "scripts/README.md"):
            with self.subTest(path=expected):
                self.assertIn(expected, names)

    def test_the_scan_reaches_a_script_a_shell_file_and_a_text_file_by_name(self):
        """Named one by one, so a change that narrows the scan back to a suffix
        list fails here. A `.py` file is where the last leak sat."""
        names = {str(p) for p in scanned_files()}
        for expected in ("scripts/bootstrap.py", "bootstrap.sh",
                         "scripts/open-items-files.txt",
                         "bootstrap.settings.json", "AGENTS.md"):
            with self.subTest(path=expected):
                self.assertIn(expected, names)

    def test_the_scan_reaches_every_suffix_this_repository_tracks(self):
        """Including the suffixes the by-name test above cannot pin, such as
        `.toml`, whose only tracked files sit under a directory a derived
        workbench may delete."""
        scanned = {p.suffix for p in scanned_files()}
        for suffix in {p.suffix for p in tracked_paths()}:
            with self.subTest(suffix=suffix or "no suffix"):
                self.assertIn(suffix, scanned, f"no {suffix} file is scanned")

    def test_every_tracked_file_is_readable_as_utf8_text(self):
        """A binary addition would be skipped in silence, so it fails here
        instead. Nothing tracked in this template is binary."""
        self.assertEqual([str(p) for p in unreadable_files()], [])

    def test_the_exemption_is_one_tracked_file_and_nothing_else(self):
        self.assertEqual(len(EXEMPT), 1)
        for rel in EXEMPT:
            with self.subTest(path=rel):
                self.assertIn(rel, set(tracked_paths()))


class PatternTests(unittest.TestCase):
    """Each pattern, against text that must match and text that must not. A
    check that silently stopped matching would pass the scan below."""

    def test_the_uuid_pattern_matches_a_uuid_and_nothing_ordinary(self):
        self.assertTrue(UUID.search(f"companyId: {SAMPLE_UUID}"))
        self.assertFalse(UUID.search("<company-uuid>"))
        self.assertFalse(UUID.search("2026-09-27 is a date"))

    def test_the_snowflake_pattern_matches_an_id_and_nothing_ordinary(self):
        self.assertTrue(SNOWFLAKE.search(f"guild {SAMPLE_SNOWFLAKE}"))
        self.assertFalse(SNOWFLAKE.search("<guild id>"))
        self.assertFalse(SNOWFLAKE.search("port 3100, version 2026.916.1"))

    def test_the_snowflake_pattern_matches_an_id_that_does_not_lead_with_one(self):
        """Six years of IDs led with a digit other than 1. The pattern read
        `\\b1\\d{16,19}\\b` and saw none of them."""
        for sample in (SAMPLE_SNOWFLAKE_2016, SAMPLE_SNOWFLAKE_2018,
                       SAMPLE_SNOWFLAKE_2021):
            with self.subTest(sample=sample):
                self.assertFalse(sample.startswith("1"))
                self.assertTrue(SNOWFLAKE.search(f"guild {sample}"))

    def test_the_samples_date_from_the_years_the_old_pattern_missed(self):
        """The dates come out of the value, not out of a comment."""
        self.assertEqual(snowflake_time(SAMPLE_SNOWFLAKE_2016).year, 2016)
        self.assertEqual(snowflake_time(SAMPLE_SNOWFLAKE_2018).year, 2018)
        self.assertEqual(snowflake_time(SAMPLE_SNOWFLAKE_2021).year, 2021)

    def test_an_id_minted_before_the_nineteen_digit_era_has_eighteen_digits(self):
        """The value passed 19 digits in July 2022, which is why every ID after
        that leads with a 1 and the old pattern looked correct."""
        for sample in (SAMPLE_SNOWFLAKE_2016, SAMPLE_SNOWFLAKE_2018,
                       SAMPLE_SNOWFLAKE_2021):
            with self.subTest(sample=sample):
                self.assertEqual(len(sample), 18)
        self.assertEqual(len(snowflake_for(2023, 1, 1)), 19)
        self.assertTrue(snowflake_for(2023, 1, 1).startswith("1"))

    def test_the_home_path_pattern_matches_a_real_path_and_not_a_placeholder(self):
        self.assertTrue(HOME_PATH.search("/Users/someone/Projects/Code"))
        self.assertTrue(HOME_PATH.search("/home/someone/projects"))
        self.assertFalse(HOME_PATH.search("/Users/<name>/Projects"))
        self.assertFalse(HOME_PATH.search("/home/<name>"))
        self.assertFalse(HOME_PATH.search("~/Library/LaunchAgents"))

    def test_the_discord_token_pattern_matches_a_token_and_not_a_file_name(self):
        self.assertTrue(DISCORD_TOKEN.search(
            f"DISCORD_BOT_SYSTEM={SAMPLE_DISCORD_TOKEN}"))
        self.assertFalse(DISCORD_TOKEN.search(
            "docs/setup/discord-agent-bots.md is a runbook"))
        self.assertFalse(DISCORD_TOKEN.search(
            "DISCORD_BOT_SYSTEM=<token>, written unquoted"))
        self.assertFalse(DISCORD_TOKEN.search("scripts.tests.test_public_scrub"))

    def test_the_discord_token_first_segment_is_not_the_snowflake_digits(self):
        """Which is why the snowflake pattern does not catch a bot token."""
        first = SAMPLE_DISCORD_TOKEN.split(".")[0]
        padded = first + "=" * (-len(first) % 4)
        self.assertEqual(base64.urlsafe_b64decode(padded).decode(), SAMPLE_SNOWFLAKE)
        self.assertFalse(SNOWFLAKE.search(first))

    def test_the_github_token_pattern_matches_each_prefix_and_nothing_ordinary(self):
        for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
            with self.subTest(prefix=prefix):
                self.assertTrue(GITHUB_TOKEN.search(prefix + "A1" * 18))
        self.assertFalse(GITHUB_TOKEN.search("gh pr ready, then gh pr view"))
        self.assertFalse(GITHUB_TOKEN.search("ghp_<token>"))

    def test_the_openai_key_pattern_matches_a_key_and_not_an_ordinary_word(self):
        self.assertTrue(OPENAI_KEY.search(f"OPENAI_API_KEY={SAMPLE_OPENAI_KEY}"))
        self.assertFalse(OPENAI_KEY.search("a risk-free change to the task-list"))
        self.assertFalse(OPENAI_KEY.search("sk-<key>"))

    def test_the_slack_token_pattern_matches_each_prefix_and_nothing_ordinary(self):
        for prefix in ("xoxb-", "xoxp-", "xoxa-", "xoxr-", "xoxs-"):
            with self.subTest(prefix=prefix):
                self.assertTrue(SLACK_TOKEN.search(prefix + "1" * 13))
        self.assertFalse(SLACK_TOKEN.search("the channel is #xoxo and it posts"))
        self.assertFalse(SLACK_TOKEN.search("xoxb-<token>"))

    def test_the_private_key_pattern_matches_every_header_form(self):
        for header in ("-----BEGIN PRIVATE KEY-----",
                       "-----BEGIN RSA PRIVATE KEY-----",
                       "-----BEGIN EC PRIVATE KEY-----",
                       SAMPLE_PRIVATE_KEY):
            with self.subTest(header=header):
                self.assertTrue(PRIVATE_KEY.search(header))
        self.assertFalse(PRIVATE_KEY.search("the file begins with a private key"))
        self.assertFalse(PRIVATE_KEY.search("-----BEGIN CERTIFICATE-----"))

    def test_both_webhook_hosts_are_banned_including_the_legacy_one(self):
        """A webhook URL minted before the domain migration still works at
        `discordapp.com`, so covering one host covered neither."""
        self.assertEqual(banned_hits("https://discord.com/api/webhooks/2/xyz"),
                         ["discord.com/api/webhooks"])
        self.assertEqual(banned_hits("https://discordapp.com/api/webhooks/2/xyz"),
                         ["discordapp.com/api/webhooks"])
        self.assertEqual(banned_hits("HTTPS://DISCORD.COM/API/WEBHOOKS/2/XYZ"),
                         ["discord.com/api/webhooks"])
        self.assertEqual(banned_hits("the server runbook creates the channels"), [])

    def test_the_word_reader_handles_comments_and_blank_lines(self):
        self.assertEqual(scrub_words(), [])


class ScrubTests(unittest.TestCase):
    """The scan itself. One subtest per file, so a failure names the file."""

    def test_no_file_carries_a_uuid(self):
        for rel in scanned_files():
            with self.subTest(path=rel):
                found = UUID.search(file_text(rel))
                self.assertIsNone(found, f"carries an identifier: {found and found.group()}")

    def test_no_file_carries_a_discord_snowflake(self):
        for rel in scanned_files():
            with self.subTest(path=rel):
                found = SNOWFLAKE.search(file_text(rel))
                self.assertIsNone(found, f"carries a Discord ID: {found and found.group()}")

    def test_no_file_carries_an_absolute_home_directory_path(self):
        """A home path names the owner of the machine, and it also makes the
        file wrong on anyone else's."""
        for rel in scanned_files():
            with self.subTest(path=rel):
                found = HOME_PATH.search(file_text(rel))
                self.assertIsNone(found, f"carries a home path: {found and found.group()}")

    def test_no_file_carries_a_credential(self):
        """The rule these runbooks state is that no token reaches a tracked
        file. This is the check for it."""
        for rel in scanned_files():
            text = file_text(rel)
            for name, pattern in CREDENTIALS:
                found = pattern.search(text)
                with self.subTest(path=rel, shape=name):
                    self.assertIsNone(found, f"carries {name}")

    def test_no_file_carries_a_scrub_word(self):
        words = scrub_words()
        if not words:
            self.skipTest("scrub-words.txt is empty; a derived workbench fills it in")
        pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b",
                             re.IGNORECASE)
        for rel in scanned_files():
            with self.subTest(path=rel):
                found = pattern.search(file_text(rel))
                self.assertIsNone(found, f"names {found and found.group()!r}")

    def test_no_file_carries_a_banned_substring(self):
        for rel in scanned_files():
            with self.subTest(path=rel):
                self.assertEqual(banned_hits(file_text(rel)), [])

    def test_the_scrub_word_list_is_readable_and_ships_empty(self):
        """The reader must handle comments, blanks, and the shipped empty file.
        A template that shipped words would be the leak it checks for."""
        self.assertTrue(SCRUB_WORDS_FILE.is_file(), "scrub-words.txt is missing")
        self.assertEqual(scrub_words(), [])
        self.assertIn("#", SCRUB_WORDS_FILE.read_text())


if __name__ == "__main__":
    unittest.main()
