"""Tests for scripts/check-open-items.py against the acceptance criteria in
SPEC.md, section "Harden the open_items parser". Most docstrings name the
criterion number they cover. Some pin a regression class named in the SPEC
prose but not itself numbered, a boundary case (empty, one item, two items),
or a CLI validation SPEC.md does not enumerate by criterion; those name what
they pin in place of a number rather than force one that does not fit.

Standard library only: unittest, tempfile, pathlib, datetime. Run with:

    python3 -m unittest discover -s scripts/tests

check-open-items.py is never edited by this file. A failing test is a finding
about the script, not a reason to change the assertion.

Fixtures are built in a temporary directory. The one test that reads the live
tree (criterion 53's regression note) asserts only that the run does not
raise and reads the number of files scripts/open-items-files.txt names, never
an item count, because item counts on the live tree go stale as items close.
"""

import contextlib
import datetime
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check-open-items.py"
CONTAINER_ROOT = SCRIPT_PATH.parent.parent

_spec = importlib.util.spec_from_file_location("check_open_items", SCRIPT_PATH)
coi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coi)

TODAY = datetime.date(2026, 9, 11)


def item_block(id_="sample-item", opened="2026-01-01", checked="2026-01-01",
               triggers="[a trigger]", asks='""', para="One line of paragraph text."):
    """One well-formed item, in the one accepted shape, as a block of text."""
    return (
        f"  - id: {id_}\n"
        f"    opened: {opened}\n"
        f"    checked: {checked}\n"
        f"    triggers: {triggers}\n"
        f"    asks: {asks}\n"
        f"    item: >\n"
        f"      {para}\n"
    )


def wrapped(body, before="", after=""):
    """One frontmatter block holding `open_items:` and the given item body."""
    return f"---\n{before}open_items:\n{body}{after}---\n"


class CheckOpenItemsTest(unittest.TestCase):
    def _root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def _write(self, root, rel, text):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _write_bytes(self, root, rel, data):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _run(self, root, given, today=TODAY, stale_days=coi.STALE_DAYS):
        return coi.run(root, given, today, stale_days)

    def _quiet_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = coi.main(argv)
        return code, buf.getvalue()

    # ---- what the script accepts (criteria 1-11) --------------------------

    def test_the_accepted_form_parses_with_no_failures(self):
        """Criterion 1: the block exactly as the schema's example states parses clean."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block()))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual(len(items), 1)

    def test_open_items_only_read_inside_frontmatter(self):
        """Criterion 2: an open_items: block in the body, not between the
        first and second bare ---, is not read as an item."""
        root = self._root()
        text = "---\nname: x\n---\n\nSome prose.\n\nopen_items:\n  - id: nope\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(items, [])
        self.assertTrue(any("outside frontmatter" in q for q in questions))

    def test_id_accepted_as_lowercase_hyphenated_slug(self):
        """Criterion 3: id matching the lowercase-hyphen pattern parses."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(id_="a1-b2-c3")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(items[0]["id"], "a1-b2-c3")

    def test_opened_and_checked_accepted_as_real_calendar_dates(self):
        """Criterion 4: valid YYYY-MM-DD dates parse into date objects."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-02-01", checked="2026-02-15")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(items[0]["opened"], datetime.date(2026, 2, 1))
        self.assertEqual(items[0]["checked"], datetime.date(2026, 2, 15))

    def test_triggers_accepted_as_single_line_flow_sequence_with_quotes_stripped(self):
        """Criterion 5: a bracketed, comma-separated list on one line parses,
        and a quoted entry keeps its text with the quotes removed."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(triggers='[first phrase, "second phrase"]')))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(items[0]["triggers"], ["first phrase", "second phrase"])

    def test_asks_empty_string_accepted_as_empty(self):
        """Criterion 6: asks: "" means empty, not a two-character string."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(asks='""')))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(items[0]["asks"], "")

    def test_asks_non_empty_value_accepted_as_written(self):
        """Criterion 6: a real question on the key's own line is a non-empty string."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(asks="Which of the two should ship?")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(items[0]["asks"], "Which of the two should ship?")

    def test_item_paragraph_across_two_continuation_lines_is_joined_by_a_space(self):
        """Criterion 7: item: > with more than one continuation line joins them."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      First line of the\n"
            "      paragraph continues here.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(items[0]["paragraph"], "First line of the paragraph continues here.")

    def test_unrelated_top_level_key_above_open_items_is_ignored(self):
        """Criterion 8: name/description above open_items: never produce a finding."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(), before="name: x\ndescription: y\n"))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(len(items), 1)

    def test_top_level_key_after_the_block_ends_it_and_is_not_read_as_a_field(self):
        """Criterion 9: a key at column 0 after open_items: stops the block."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(), after="another_key: z\n"))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(len(items), 1)

    def test_frontmatter_with_no_open_items_key_reports_zero_items_and_nothing_else(self):
        """Criterion 10: not every context file carries an item; that is a
        pass. A second file that does declare keeps `declaring` above zero
        for the run, so criterion 43's separate whole-run question does not
        also fire and mask what this test checks."""
        root = self._root()
        self._write(root, "a.md", "---\nname: x\ndescription: y\n---\nBody.\n")
        self._write(root, "b.md", wrapped(item_block()))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md", "b.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(declaring, 1)

    def test_blank_line_inside_the_block_is_ignored_and_does_not_end_the_item(self):
        """Criterion 11: a blank line inside open_items: is not a refusal."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(len(items), 1)

    # ---- the empty and boundary cases --------------------------------------

    def test_open_items_block_that_yields_no_item_is_a_failure(self):
        """A declared block with zero entries used to pass. It is a failure now."""
        root = self._root()
        self._write(root, "a.md", "---\nopen_items:\nother_key: z\n---\n")
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertIn("a.md: declares open_items: and yields no item", failures)

    def test_one_item_file_parses_to_exactly_one_item(self):
        """The one-item case: exactly one item comes back, no more, no less."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(id_="only-one")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual([i["id"] for i in items], ["only-one"])

    def test_two_items_in_one_file_both_parse(self):
        """More than one entry in a block: both parse and keep their own id."""
        root = self._root()
        body = item_block(id_="first-item") + item_block(id_="second-item")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual([i["id"] for i in items], ["first-item", "second-item"])

    def test_no_file_read_at_all_declares_open_items_is_a_question(self):
        """Criterion 43: the whole-run empty case is a question, not silence."""
        root = self._root()
        self._write(root, "a.md", "---\nname: x\n---\nBody.\n")
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("no file read declares open_items:" in q for q in questions))
        self.assertIn("1 file(s) read", questions[0])

    # ---- whitespace and line endings ---------------------------------------

    def test_crlf_line_endings_are_refused_by_name(self):
        """Criterion 14. Regression: newline='' must keep \\r visible, or a
        CRLF file reads as zero items and passes, which is the old defect."""
        root = self._root()
        text = wrapped(item_block()).replace("\n", "\r\n")
        self._write_bytes(root, "a.md", text.encode("utf-8"))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("CRLF" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_utf8_bom_is_refused_by_name_and_not_also_as_no_frontmatter(self):
        """Criterion 13: a BOM gets its own message, never the generic one."""
        root = self._root()
        text = "﻿" + wrapped(item_block())
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("byte order mark" in f for f in failures), failures)
        self.assertFalse(any("no frontmatter" in f for f in failures))

    def test_tab_anywhere_in_the_block_is_refused(self):
        """Criterion 15: a tab character in the block is refused, citing the spec."""
        root = self._root()
        body = item_block().replace("    opened:", "\topened:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("tab character" in f for f in failures), failures)

    def test_file_with_no_trailing_newline_after_the_closing_fence_still_parses(self):
        """Not in SPEC's list by number, but the class that has bitten this
        codebase before. A file whose last byte
        is the closing --- with no newline after it must not be read as
        having no frontmatter."""
        root = self._root()
        text = wrapped(item_block())
        assert text.endswith("---\n")
        text = text[:-1]  # drop the final newline only
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(len(items), 1)

    def test_trailing_whitespace_on_a_key_line_does_not_break_parsing(self):
        """A line a human wrote with trailing spaces should not be refused for
        indentation it does not carry: leading() only counts leading spaces."""
        root = self._root()
        body = item_block().replace("    opened: 2026-01-01\n", "    opened: 2026-01-01   \n")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])

    # ---- encoding -----------------------------------------------------------

    def test_non_utf8_file_is_a_failure_naming_it(self):
        """Criterion 40: invalid UTF-8 bytes get their own message."""
        root = self._root()
        self._write_bytes(root, "a.md", b"\x80\x81\x82 not utf8 at all")
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertIn("a.md: is not UTF-8 text", failures)

    # ---- the wrong thing at a path ------------------------------------------

    def test_path_that_does_not_exist_is_a_failure_naming_it(self):
        """Criterion 39: a missing path is never skipped in silence."""
        root = self._root()
        failures, questions, due, items, files, declaring = self._run(root, ["nowhere.md"])
        self.assertTrue(any("no such file or directory" in f for f in failures), failures)

    def test_dangling_symlink_path_is_a_failure_naming_it(self):
        """A path that vanished, modelled as a symlink to nothing: stat()
        raises on it, so it must land in the same failure as a missing path,
        not raise."""
        root = self._root()
        target = root / "a.md"
        try:
            target.symlink_to(root / "does-not-exist.md")
        except OSError as exc:
            self.skipTest(f"symlinks not supported here: {exc}")
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("no such file or directory" in f for f in failures), failures)

    def test_directory_argument_reads_every_markdown_file_below_it(self):
        """A directory path is not refused; every *.md file below it is checked."""
        root = self._root()
        self._write(root, "sub/a.md", wrapped(item_block(id_="one-here")))
        self._write(root, "sub/b.md", wrapped(item_block(id_="two-here")))
        self._write(root, "sub/not-markdown.txt", "ignored\n")
        failures, questions, due, items, files, declaring = self._run(root, ["sub"])
        self.assertEqual(failures, [])
        self.assertEqual(len(files), 2)
        self.assertEqual(sorted(i["id"] for i in items), ["one-here", "two-here"])

    def test_unreadable_file_reports_cannot_be_read_with_the_error_type(self):
        """Criterion 40: an OSError raised while opening the file (not while
        locating it) is reported, naming the error type, never a raised
        traceback. chmod 0 reaches the open()-time branch; a dangling or
        self-referential symlink does not, because gather() calls entry_kind()
        first and it reports a path stat() will not describe (see the next
        test)."""
        root = self._root()
        import os
        path = self._write(root, "noperm.md", wrapped(item_block()))
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o644)
        failures, questions, due, items, files, declaring = self._run(root, ["noperm.md"])
        matches = [f for f in failures if f.startswith("noperm.md")]
        self.assertEqual(len(matches), 1)
        self.assertIn("cannot be read,", matches[0])

    def test_self_referential_symlink_as_an_explicit_path_is_reported_missing(self):
        """A self-referential symlink makes stat() raise, so entry_kind()
        answers UNREADABLE; gather() treats that the same as absent and reports
        the criterion 39 message, never a traceback and never the open()-time
        message above."""
        root = self._root()
        loop = root / "loop.md"
        try:
            loop.symlink_to(loop)
        except OSError as exc:
            self.skipTest(f"symlinks not supported here: {exc}")
        failures, questions, due, items, files, declaring = self._run(root, ["loop.md"])
        self.assertTrue(any(f.startswith("loop.md") and "no such file or directory" in f for f in failures), failures)

    def test_unreadable_file_inside_a_walked_directory_is_a_failure_naming_it(self):
        """Criterion 39, through a directory argument: a self-referential
        symlink named *.md inside a walked directory gets the same message as
        a path argument that does not resolve, and stays in the file count.

        The walk used to filter rglob() through p.is_file(), which answers
        False for an entry whose stat() raises, so the entry reached neither
        the failure list nor the count. entry_kind() reports it instead."""
        root = self._root()
        sub = root / "sub"
        sub.mkdir()
        loop = sub / "loop.md"
        try:
            loop.symlink_to(loop)
        except OSError as exc:
            self.skipTest(f"symlinks not supported here: {exc}")
        self._write(root, "sub/ok.md", wrapped(item_block()))
        failures, questions, due, items, files, declaring = self._run(root, ["sub"])
        self.assertEqual(len(files), 2)  # ok.md and loop.md, which is counted, not dropped
        matches = [f for f in failures if "loop.md" in f]
        self.assertEqual(matches, ["sub/loop.md: no such file or directory"])

    def test_unlistable_directory_is_a_failure_naming_it(self):
        """walk()'s fix for rglob(), which swallows PermissionError and
        yields nothing: an unreadable directory holding a valid item file
        used to read as zero files and no finding. It is a failure naming
        the path and the error type instead."""
        root = self._root()
        import os
        if os.getuid() == 0:
            self.skipTest("running as root: chmod 000 does not restrict root")
        sub = root / "sub"
        sub.mkdir()
        self._write(root, "sub/ok.md", wrapped(item_block()))
        os.chmod(sub, 0o000)
        self.addCleanup(os.chmod, sub, 0o755)
        failures, questions, due, items, files, declaring = self._run(root, ["sub"])
        self.assertTrue(any("sub" in f and "cannot be listed" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_walk_does_not_descend_into_a_symlinked_subdirectory(self):
        """A subdirectory reached through a symlink is not walked, which is
        what stops a link pointing back up the tree from recursing forever.
        The owner changed the behaviour on 2026-09-12: the skip is reported as a
        question naming the symlinked path, not silence, because a symlinked
        directory answers stat() fine and the walk declines to read it by
        design, which is a question and not a failure about the tree being
        wrong. A second, real file is passed alongside the symlinked one so
        criterion 43's separate whole-run question does not also fire and
        mask the message this test pins."""
        root = self._root()
        real = root / "real"
        real.mkdir()
        self._write(root, "real/inside.md", wrapped(item_block(id_="inside-real")))
        sub = root / "sub"
        sub.mkdir()
        link = sub / "linked"
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlinks not supported here: {exc}")
        self._write(root, "ok.md", wrapped(item_block(id_="kept")))
        failures, questions, due, items, files, declaring = self._run(root, ["sub", "ok.md"])
        self.assertEqual(files, [root / "ok.md"])  # not descended: only ok.md read
        self.assertEqual([i["id"] for i in items], ["kept"])
        self.assertEqual(failures, [])
        self.assertEqual(
            questions,
            [
                "sub/linked: a symlinked directory, which the walk never follows, so no file "
                "under it is read. Name this path in scripts/open-items-files.txt if it should be read."
            ],
        )
        code, _ = self._quiet_main(["prog", "--root", str(root), str(root / "sub"), str(root / "ok.md")])
        self.assertEqual(code, 1)

    # ---- frontmatter shape refusals -----------------------------------------

    # Criterion 12 was rewritten on 2026-09-11 into three cases, each with one
    # finding and no other. The message `no frontmatter, or --- is not the first
    # line` went with the old rule, so nothing below asserts it.

    def test_no_frontmatter_and_no_open_items_anywhere_is_silent(self):
        """Criterion 12(a): a missing frontmatter is not a defect. The schema
        asks for frontmatter only in a file where an item lives, and
        roots/AGENTS.md on the live tree carries none since its item closed."""
        root = self._root()
        self._write(root, "a.md", "# a context file\n\nProse, and no open item.\n")
        self._write(root, "b.md", wrapped(item_block()))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md", "b.md"])
        self.assertEqual([f for f in failures if f.startswith("a.md")], [])
        self.assertEqual([q for q in questions if q.startswith("a.md")], [])

    def test_no_frontmatter_with_a_column_zero_open_items_is_one_question(self):
        """Criterion 12(b): the block is outside frontmatter, so it is unread,
        and open question 2's settled answer makes it a question rather than a
        failure. One question, no failure, and the file is not half-read."""
        root = self._root()
        self._write(root, "a.md", "# a context file\n\nopen_items:\n  - id: x\n")
        self._write(root, "b.md", wrapped(item_block()))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md", "b.md"])
        self.assertEqual([f for f in failures if f.startswith("a.md")], [])
        matches = [q for q in questions if q.startswith("a.md")]
        self.assertEqual(len(matches), 1)
        self.assertIn("outside frontmatter", matches[0])
        self.assertEqual([i["file"] for i in items], ["b.md"])  # a.md yields nothing

    def test_frontmatter_opened_and_never_closed_is_one_failure_and_no_question(self):
        """Criterion 12(c): one defect earns one finding. The failure names the
        line the frontmatter opened on, and the stray scan is not also run, so
        the exit code carries one, not two."""
        root = self._root()
        self._write(root, "a.md", "---\nopen_items:\n  - id: x\n")
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, ["a.md:1: frontmatter with no closing ---, so nothing in it is read"])
        self.assertEqual([q for q in questions if q.startswith("a.md")], [])

    def test_open_items_at_column_zero_outside_frontmatter_is_a_question_and_other_files_still_read(self):
        """Question case: it blocks and does not stop other files being read,
        and it names no wrongness about the file."""
        root = self._root()
        self._write(root, "example.md", "# doc\n\nopen_items:\n  - id: example\n")
        self._write(root, "real.md", wrapped(item_block(id_="real-one")))
        failures, questions, due, items, files, declaring = self._run(root, ["example.md", "real.md"])
        self.assertTrue(any("example.md" in q and "outside frontmatter" in q for q in questions))
        self.assertEqual([i["id"] for i in items], ["real-one"])

    def test_open_items_with_a_value_on_its_own_line_is_refused(self):
        """Criterion 16: open_items: [] and any other same-line value refused."""
        root = self._root()
        self._write(root, "a.md", "---\nopen_items: []\n---\n")
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("open_items: with a value on its own line" in f for f in failures), failures)
        self.assertEqual(items, [])

    # ---- the open_items key itself, refused by shape --------------------------
    # Each of these three was a silent drop until the builder named it: a leading
    # space on the real AGENTS.md dropped six items with exit 0. Each fixture
    # carries a second, valid file, so the specific refusal is what fires and
    # never gets confused with the generic "no file declares open_items:"
    # question that a lone broken file could mask it behind.

    def test_open_items_key_at_indent_one_is_refused_naming_the_indent(self):
        """A leading space before `open_items:` is refused, naming the indent
        and the accepted column-0 form. The file still counts as declaring, so
        it also fails for yielding no item: the drop is impossible now."""
        root = self._root()
        broken = "---\n open_items:\n" + item_block() + "---\n"
        self._write(root, "broken.md", broken)
        self._write(root, "ok.md", wrapped(item_block(id_="ok-one")))
        failures, questions, due, items, files, declaring = self._run(root, ["broken.md", "ok.md"])
        self.assertTrue(any("`open_items` at indent 1" in f and "column 0" in f for f in failures), failures)
        self.assertTrue(any(f.startswith("broken.md") and "yields no item" in f for f in failures), failures)
        self.assertEqual([i["id"] for i in items], ["ok-one"])
        self.assertEqual(questions, [])

    def test_tab_before_open_items_key_is_refused_as_a_tab_not_an_indent(self):
        """A tab-led `open_items:` key gets the tab message, never the indent
        message: the two name different fixes, so the wrong one sends a reader
        to edit the wrong thing."""
        root = self._root()
        broken = "---\n\topen_items:\n" + item_block() + "---\n"
        self._write(root, "broken.md", broken)
        self._write(root, "ok.md", wrapped(item_block(id_="ok-one")))
        failures, questions, due, items, files, declaring = self._run(root, ["broken.md", "ok.md"])
        self.assertTrue(any("a tab before `open_items`" in f for f in failures), failures)
        self.assertFalse(any(f.startswith("broken.md") and "at indent" in f for f in failures), failures)
        self.assertTrue(any(f.startswith("broken.md") and "yields no item" in f for f in failures), failures)
        self.assertEqual([i["id"] for i in items], ["ok-one"])

    def test_open_items_with_no_colon_is_refused_as_not_a_key(self):
        """`open_items` with the colon left off is refused as not being a key
        at all, distinct from the indent and tab messages above."""
        root = self._root()
        broken = "---\nopen_items\n" + item_block() + "---\n"
        self._write(root, "broken.md", broken)
        self._write(root, "ok.md", wrapped(item_block(id_="ok-one")))
        failures, questions, due, items, files, declaring = self._run(root, ["broken.md", "ok.md"])
        self.assertTrue(any("`open_items` with no colon, so it is not a key" in f for f in failures), failures)
        self.assertTrue(any(f.startswith("broken.md") and "yields no item" in f for f in failures), failures)
        self.assertEqual([i["id"] for i in items], ["ok-one"])

    def test_indented_open_items_with_no_colon_is_refused_via_the_end_of_line_branch(self):
        """Criterion 67's indented rule, the `$` half: `  open_items` at
        indent 2 with the colon left off and nothing else on the line. The
        indented matcher is `^open_items[ \\t]*(:|$)`; narrowing it to
        `(:)` alone leaves this line unmatched by either regex (the
        top-level regex is anchored at column 0 and this line is indented),
        so the block is read as ordinary skipped content and the whole item
        below it vanishes with no failure and no question. This is the one
        live silent drop with no other test in this file. The refusal must
        be the indent message (criterion 64's shape, since indent is
        non-zero), paired with criterion 41's yields-no-item failure, and a
        second, valid file must still parse so the drop is not masked by
        criterion 43's whole-run question."""
        root = self._root()
        broken = "---\n  open_items\n" + item_block() + "---\n"
        self._write(root, "broken.md", broken)
        self._write(root, "ok.md", wrapped(item_block(id_="ok-one")))
        failures, questions, due, items, files, declaring = self._run(root, ["broken.md", "ok.md"])
        self.assertTrue(any("`open_items` at indent 2" in f for f in failures), failures)
        self.assertTrue(any(f.startswith("broken.md") and "yields no item" in f for f in failures), failures)
        self.assertEqual([i["id"] for i in items], ["ok-one"])
        self.assertEqual(questions, [])
        code, _ = self._quiet_main(["prog", "--root", str(root), str(root / "broken.md"), str(root / "ok.md")])
        self.assertEqual(code, 2)  # the indent refusal plus criterion 41's yields-no-item

    # ---- a top-level `open_items` followed by text and no colon -------------
    # The fourth silent drop, settled by the owner on 2026-09-12: "refuse it only
    # at the top level of frontmatter, never inside a block." Before the fix
    # this line was read as the content of some other block, every item under
    # it was dropped, and the run exited 0.

    def test_open_items_followed_by_text_and_no_colon_is_refused_by_name(self):
        """A top-level `open_items` with trailing text and no colon is refused
        naming that text, exactly, and pairs with criterion 41: two failures,
        zero questions, exit 2. A count-only assertion would also pass a
        refusal that named the wrong shape."""
        root = self._root()
        broken = "---\nopen_items delete this text\n" + item_block() + "---\n"
        self._write(root, "broken.md", broken)
        failures, questions, due, items, files, declaring = self._run(root, ["broken.md"])
        self.assertEqual(
            failures,
            [
                "broken.md:2: `open_items` followed by 'delete this text' and no colon, so the "
                "line is not a key. Write `open_items:` at column 0 with nothing after the colon, "
                "then one `  - id: slug` line per item.",
                "broken.md: declares open_items: and yields no item",
            ],
        )
        self.assertEqual(questions, [])
        self.assertEqual(items, [])
        code, _ = self._quiet_main(["prog", "--root", str(root), str(root / "broken.md")])
        self.assertEqual(code, 2)

    def test_same_text_inside_a_folded_value_still_parses(self):
        """The asymmetry that matters more than the refusal. The identical
        words that are refused at column 0, `open_items delete this text`,
        report nothing when a folded value under a different key wraps a
        line onto them, and the real block below still parses. This fails
        loudly if the column-0-only matcher is ever applied to an indented
        line: that line has no colon after the name, so only the wider
        matcher would catch it, and it must not."""
        root = self._root()
        text = (
            "---\n"
            "description: >\n"
            "  A paragraph that happens to wrap onto the words\n"
            "  open_items delete this text elsewhere in the tree.\n"
            "open_items:\n" + item_block() + "---\n"
        )
        self._write(root, "ok.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["ok.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual([i["id"] for i in items], ["sample-item"])

    def test_a_longer_key_beside_a_real_block_is_never_reported(self):
        """Criterion 8: another top-level key is never reported, even one
        that shares the name as a prefix. `open_items_log:` beside a real
        `open_items:` block must not trip the new column-0 matcher."""
        root = self._root()
        text = (
            "---\n"
            "open_items_log: something\n"
            "open_items:\n"
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      One line.\n"
            "---\n"
        )
        self._write(root, "ok.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["ok.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual([i["id"] for i in items], ["sample-item"])

    def test_the_four_key_shape_messages_are_each_distinct(self):
        """The indented key, the tab-led key, the bare colonless key, and the
        text-with-no-colon key each carry their own message. The new shape's
        message is not one of the other three's, and the bare-key message
        stays byte-identical to what criterion 66 already fixed."""
        root = self._root()
        fixtures = {
            "indent.md": "---\n open_items:\n" + item_block() + "---\n",
            "tab.md": "---\n\topen_items:\n" + item_block() + "---\n",
            "bare.md": "---\nopen_items\n" + item_block() + "---\n",
            "text.md": "---\nopen_items delete this text\n" + item_block() + "---\n",
        }
        for name, text in fixtures.items():
            self._write(root, name, text)
        failures, questions, due, items, files, declaring = self._run(root, list(fixtures))
        key_lines = [f for f in failures if ":2: " in f]
        self.assertEqual(len(key_lines), 4, failures)
        messages = {f.split(":2: ", 1)[1] for f in key_lines}
        self.assertEqual(len(messages), 4, "each fixture's key-line message must be unique")
        bare_message = next(f for f in key_lines if f.startswith("bare.md"))
        self.assertEqual(
            bare_message,
            "bare.md:2: `open_items` with no colon, so it is not a key. Write `open_items:` at "
            "column 0 with nothing after the colon, then one `  - id: slug` line per item.",
        )

    # ---- criterion 8 and 67(d)/(e)/68: the class of legal suffixes, not one member -
    # The rule inverted on 2026-09-12 because no finite exclusion list is right: a
    # plain YAML key may carry almost any printable character. Each of these is a
    # different top-level key and criterion 8 says it is never reported, whatever it
    # is followed by.

    def test_open_items_hyphen_suffix_key_is_never_reported(self):
        """Criteria 8 and 67(e): `open_items-log:` is a different key. A
        hyphen-only fix (the rule the owner rejected) would still refuse this."""
        root = self._root()
        text = "---\nopen_items-log: something\nopen_items:\n" + item_block() + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual([i["id"] for i in items], ["sample-item"])

    def test_open_items_dot_suffix_key_is_never_reported(self):
        """Criteria 8 and 67(e): `open_items.log:` is a different key. This is
        the case a hyphen-only exclusion fix would still have missed."""
        root = self._root()
        text = "---\nopen_items.log: something\nopen_items:\n" + item_block() + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual([i["id"] for i in items], ["sample-item"])

    def test_open_items_at_sign_suffix_key_is_never_reported(self):
        """Criterion 8, a fourth legal suffix chosen for this suite: `@` is one
        of YAML's own indicator characters, restricted only where it opens a
        plain scalar, so `open_items@log:` is still a legal, different key.
        Nobody drafting an exclusion list would think to add `@`, which is the
        whole case against that approach."""
        root = self._root()
        text = "---\nopen_items@log: something\nopen_items:\n" + item_block() + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual([i["id"] for i in items], ["sample-item"])

    # ---- criterion 67: the terminator set is exactly space, tab, colon, end -----
    # Tested as a property: every character that ends the name is one of four,
    # and a representative spread of others is not. Boundary cases are chosen so
    # that narrowing the set (dropping space, tab or end) or widening it (adding
    # a character such as hyphen) each break a specific case below.

    def test_space_after_open_items_is_a_terminator(self):
        """A space ends the name, so `open_items x` is read as our broken key
        (refused by criterion 68) rather than skipped as a different key.
        Narrowing the terminator set to drop space would make this pass
        silently instead."""
        root = self._root()
        text = "---\nopen_items x\n" + item_block("dropped") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("followed by 'x' and no colon" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_tab_after_open_items_is_a_terminator(self):
        """A tab ends the name the same way a space does. Narrowing the
        terminator set to drop tab would make `open_items\\tx` read as a
        different key and skip it."""
        root = self._root()
        text = "---\nopen_items\tx\n" + item_block("dropped") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("followed by 'x' and no colon" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_colon_after_open_items_is_a_terminator(self):
        """A colon ends the name and is the one shape the accepted form uses.
        Narrowing the set to `$` only would make `open_items:` unrecognized as
        our key, which no other test would catch once (e) exists."""
        root = self._root()
        text = "---\nopen_items:\n" + item_block("kept") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual([i["id"] for i in items], ["kept"])

    def test_end_of_line_after_open_items_is_a_terminator(self):
        """The end of the line ends the name too: bare `open_items` with
        nothing after it is our key, refused as colonless, not skipped as a
        different key with an empty name. Narrowing the set to drop `$` would
        make this line invisible to the parser."""
        root = self._root()
        text = "---\nopen_items\n" + item_block("dropped") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("with no colon, so it is not a key" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_hyphen_after_open_items_is_not_a_terminator(self):
        """A hyphen does not end the name. Widening the terminator set to
        include `-` would make `open_items-log:` read as our broken key and
        refuse a file criterion 8 promises stays silent."""
        root = self._root()
        text = "---\nopen_items-log: something\nopen_items:\n" + item_block("kept") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual([i["id"] for i in items], ["kept"])

    # ---- criterion 69: whitespace between the name and its colon ---------------
    # Added 2026-09-12. No test existed for this refusal before this suite.

    def test_space_between_open_items_and_colon_is_refused_by_its_own_message(self):
        """Criterion 69(a): `open_items :` is refused naming the whitespace,
        pairs with criterion 41, and never falls through to criterion 16's
        value message, which would tell the reader to delete a value this
        line does not carry."""
        root = self._root()
        text = "---\nopen_items :\n" + item_block("dropped") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(
            failures,
            [
                "a.md:2: a space or a tab between `open_items` and its colon. Write `open_items:` "
                "at column 0 with the colon against the name and nothing after it, then one "
                "`  - id: slug` line per item.",
                "a.md: declares open_items: and yields no item",
            ],
        )
        self.assertEqual(questions, [])
        self.assertEqual(items, [])
        self.assertFalse(any("value on its own line" in f for f in failures), failures)
        code, _ = self._quiet_main(["prog", "--root", str(root), str(root / "a.md")])
        self.assertEqual(code, 2)

    def test_tab_between_open_items_and_colon_takes_its_own_message_not_criterion_65s(self):
        """Criterion 69(b): the tab sits after the name, not in the leading
        indentation, so it takes criterion 69's message and never criterion
        65's tab-in-indentation message. The two name different fixes."""
        root = self._root()
        text = "---\nopen_items\t:\n" + item_block("dropped") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(
            any("a space or a tab between `open_items` and its colon" in f for f in failures), failures
        )
        self.assertFalse(any("a tab before `open_items`" in f for f in failures), failures)

    def test_whitespace_and_a_value_both_present_names_both_halves_of_the_edit(self):
        """Criterion 69(c): `open_items : []` carries both faults at once. The
        message must name both: the whitespace comes out and the value comes
        out. This is the check SPEC.md's own dated note says the built script
        does not yet meet, so a failure here is a finding about the script,
        not the test."""
        root = self._root()
        text = "---\nopen_items : []\n" + item_block("dropped") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        key_line = next(f for f in failures if f.startswith("a.md:2:"))
        self.assertIn("space or a tab", key_line)
        self.assertIn("[]", key_line, "the message must also name the value found, not just the space")

    # ---- criterion 41's pairing, and the second-key subtlety -------------------

    def test_a_broken_key_with_no_second_key_is_two_failures_and_exit_2(self):
        """Criterion 68's own shape: the broken key's items are consumed with
        no valid open_items: key to follow, so the file yields no item and
        criterion 41's failure fires beside the refusal. Two failures, zero
        questions, exit 2."""
        root = self._root()
        text = "---\nopen_items some trailing text\n" + item_block("dropped") + "---\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(len(failures), 2, failures)
        self.assertTrue(any("yields no item" in f for f in failures), failures)
        self.assertEqual(questions, [])
        self.assertEqual(items, [])
        code, _ = self._quiet_main(["prog", "--root", str(root), str(root / "a.md")])
        self.assertEqual(code, 2)

    def test_a_broken_key_followed_by_a_second_valid_key_parses_the_second_block(self):
        """The subtlety a later reader could misread as a bug: a second, valid
        `open_items:` key below the broken one is not consumed by the broken
        key's block-end scan, because it sits at column 0 and starts with
        neither a space nor a `-`. So it parses normally, the file yields an
        item, and criterion 41's failure never fires: one failure, zero
        questions, exit 1, not 2."""
        root = self._root()
        text = (
            "---\nopen_items some trailing text\n" + item_block("dropped")
            + "open_items:\n" + item_block("kept") + "---\n"
        )
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(len(failures), 1, failures)
        self.assertFalse(any("yields no item" in f for f in failures), failures)
        self.assertEqual(questions, [])
        self.assertEqual([i["id"] for i in items], ["kept"])
        code, _ = self._quiet_main(["prog", "--root", str(root), str(root / "a.md")])
        self.assertEqual(code, 1)

    # ---- fenced code blocks --------------------------------------------------
    # Settled by the owner on 2026-09-11: the script ignores a line inside a fenced
    # block, because a fenced `open_items:` is documentation and never was a
    # declaration. Two files on the checked list carry one.

    def test_open_items_inside_a_backtick_fenced_block_reports_nothing(self):
        """A documented example inside a ```yaml block is neither read nor
        asked about. This is the shape central-context/AGENTS.md and SPEC.md
        both carry, read 2026-09-11."""
        root = self._root()
        text = "# doc\n\n```yaml\n---\nopen_items:\n  - id: kebab-case-slug\n---\n```\n"
        self._write(root, "a.md", text)
        self._write(root, "b.md", wrapped(item_block()))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md", "b.md"])
        self.assertEqual([f for f in failures if f.startswith("a.md")], [])
        self.assertEqual([q for q in questions if q.startswith("a.md")], [])

    def test_open_items_inside_a_tilde_fenced_block_reports_nothing(self):
        """A tilde fence is the other marker CommonMark states, so it is read
        the same way. No file on this tree writes one today."""
        root = self._root()
        text = "# doc\n\n~~~yaml\nopen_items:\n  - id: kebab-case-slug\n~~~\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual([f for f in failures if f.startswith("a.md")], [])
        self.assertEqual([q for q in questions if q.startswith("a.md")], [])

    def test_open_items_after_a_closed_fence_is_still_a_question(self):
        """Both behaviours hold together: the fence exempts what is inside it
        and nothing else, so criterion 12(b) still fires below the close."""
        root = self._root()
        text = "```yaml\nopen_items:\n  - id: example\n```\n\nopen_items:\n  - id: real\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        matches = [q for q in questions if q.startswith("a.md")]
        self.assertEqual(len(matches), 1)
        self.assertIn("a.md:6:", matches[0])
        self.assertIn("outside frontmatter", matches[0])

    def test_unclosed_fence_is_one_failure_naming_the_line_it_opened_on(self):
        """The silent-drop case the fence tracker could have introduced. An
        unclosed fence puts every line below it inside a fence forever, so a
        real open_items: below would vanish with no finding. It is a failure
        instead, naming the line the fence opened on."""
        root = self._root()
        text = (
            "# doc\n"
            "\n"
            "```yaml\n"
            "open_items:\n"
            "  - id: documented-example\n"
            "\n"
            "open_items:\n"
            "  - id: a-real-block\n"
        )
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("a.md:3:", failures[0])
        self.assertIn("never closes", failures[0])
        self.assertEqual([q for q in questions if q.startswith("a.md")], [])

    def test_a_shorter_fence_inside_a_longer_one_does_not_close_it(self):
        """The closing fence is at least as long as the opening one. Without
        that test the inner three-backtick line closes the block, the outer
        four-backtick line reads as a second opening, and everything after it
        falls inside a fence that never ends."""
        root = self._root()
        text = (
            "````markdown\n"
            "```yaml\n"
            "open_items:\n"
            "  - id: example\n"
            "```\n"
            "````\n"
        )
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual([f for f in failures if f.startswith("a.md")], [])
        self.assertEqual([q for q in questions if q.startswith("a.md")], [])

    def test_a_tilde_line_does_not_close_a_backtick_fence(self):
        """Criterion 62(b): the closing fence must repeat the opening
        character. A ~~~ line inside a backtick-opened fence does not close
        it, so the fence stays open through it and a real block below is
        still hidden, reported as unclosed rather than silently dropped."""
        root = self._root()
        text = (
            "# doc\n"
            "\n"
            "```yaml\n"
            "open_items:\n"
            "  - id: example\n"
            "~~~\n"
            "open_items:\n"
            "  - id: would-be-real\n"
        )
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("never closes", failures[0])
        self.assertEqual(items, [])
        self.assertEqual([q for q in questions if q.startswith("a.md")], [])

    def test_an_indented_fence_is_not_read_as_a_fence_and_the_example_still_asks(self):
        """The stated boundary: only a marker at column 0 is read as a fence.
        A form the tracker does not cover errs toward a question, which blocks,
        and never toward a line dropped in silence."""
        root = self._root()
        text = "# doc\n\n  ```yaml\nopen_items:\n  - id: example\n  ```\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual([f for f in failures if f.startswith("a.md")], [])
        self.assertEqual(len([q for q in questions if q.startswith("a.md")]), 1)

    def test_a_fenced_example_in_the_body_leaves_frontmatter_items_parsing(self):
        """The fence scan starts below the frontmatter, so it cannot move the
        --- lines the span is read from. Real items and a documented example
        live in one file, which is what AGENTS.md will look like next."""
        root = self._root()
        text = wrapped(item_block(id_="real-one")) + "\n```yaml\nopen_items:\n  - id: example\n```\n"
        self._write(root, "a.md", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])
        self.assertEqual([i["id"] for i in items], ["real-one"])

    # ---- indentation, exactly: the dash -------------------------------------

    def test_dash_at_column_zero_is_refused_naming_the_column(self):
        """Criterion 17: column 0, one off from the accepted column 2."""
        root = self._root()
        body = item_block().replace("  - id:", "- id:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("`-` at column 0" in f for f in failures), failures)

    def test_dash_at_column_one_is_refused_naming_the_column(self):
        """One off from the accepted column, the other direction."""
        root = self._root()
        body = item_block().replace("  - id:", " - id:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("`-` at column 1" in f for f in failures), failures)

    def test_dash_at_column_three_is_refused_naming_the_column(self):
        """One off the other side of column 2."""
        root = self._root()
        body = item_block().replace("  - id:", "   - id:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("`-` at column 3" in f for f in failures), failures)

    def test_dash_at_column_four_is_refused_naming_the_column(self):
        """Criterion 17: column 4 explicitly named in the spec is tested."""
        root = self._root()
        body = item_block().replace("  - id:", "    - id:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("`-` at column 4" in f for f in failures), failures)

    def test_dash_alone_on_its_line_is_refused_as_non_compact(self):
        """Criterion 18: id: on the next line, not beside the dash."""
        root = self._root()
        body = "  -\n    id: sample-item\n    opened: 2026-01-01\n    checked: 2026-01-01\n    triggers: [t]\n    asks: \"\"\n    item: >\n      Text.\n"
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("alone on its line" in f for f in failures), failures)

    def test_flow_mapping_entry_is_refused_by_name(self):
        """Criterion 23: `- {id: x, opened: y}` is refused as a flow mapping."""
        root = self._root()
        body = "  - {id: sample-item, opened: 2026-01-01}\n"
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("flow mapping" in f for f in failures), failures)

    # ---- indentation, exactly: item keys ------------------------------------

    def test_item_key_at_indent_three_is_refused_naming_the_indent(self):
        """Criterion 20: one off from the accepted indent of four, low side."""
        root = self._root()
        body = item_block().replace("    opened:", "   opened:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("item key at indent 3" in f for f in failures), failures)

    def test_item_key_at_indent_five_is_refused_naming_the_indent(self):
        """Criterion 20: one off from four, high side."""
        root = self._root()
        body = item_block().replace("    opened:", "     opened:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("item key at indent 5" in f for f in failures), failures)

    def test_item_key_at_indent_six_is_refused_naming_the_indent(self):
        """Criterion 20: explicitly named in the spec alongside three and five."""
        root = self._root()
        body = item_block().replace("    opened:", "      opened:")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("item key at indent 6" in f for f in failures), failures)

    # ---- indentation, exactly: item's continuation line ---------------------

    def test_item_continuation_at_indent_five_is_refused_naming_the_indent(self):
        """Criterion 36: one off from the accepted six, low side."""
        root = self._root()
        body = item_block().replace("      One line", "     One line")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("continuation line at indent 5" in f for f in failures), failures)

    def test_item_continuation_at_indent_seven_is_refused_naming_the_indent(self):
        """Criterion 36: one off from six, high side."""
        root = self._root()
        body = item_block().replace("      One line", "       One line")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("continuation line at indent 7" in f for f in failures), failures)

    def test_item_header_with_no_continuation_line_at_all_is_refused_as_empty(self):
        """Criterion 36: item: > followed directly by the block end."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("no continuation line" in f for f in failures), failures)

    # ---- criterion 20(b): a key opening with a digit, `.`, `/` or `+` --------
    # YAML permits far more first characters for a plain key than KEY_LINE_RE's
    # class of letter/underscore/quote. A line outside that class is never
    # accepted and never silently skipped, only its message differs, and this
    # criterion claims no message for it: it is refused by whichever of
    # criteria 31 or 36 already owns that position. Pinned in all three
    # positions rather than one, because a positional answer would be weaker.

    def test_a_digit_led_key_shaped_line_after_triggers_takes_criterion_31_not_criterion_20(self):
        """Criterion 20(b), position 1: `2026-note: x` at indent five right
        after `triggers:` never reaches criterion 20's indent message,
        because KEY_LINE_RE does not match a name starting with a digit. It
        takes criterion 31's continuing-triggers refusal instead."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "     2026-note: x\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("continuing triggers:" in f for f in failures), failures)
        self.assertFalse(any("item key at indent" in f for f in failures), failures)

    def test_a_digit_led_key_shaped_line_after_asks_takes_criterion_31_not_criterion_20(self):
        """Criterion 20(b), position 2: the same line after `asks:` takes
        criterion 31's continuing-asks refusal, not criterion 20's."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: A real question\n"
            "     2026-note: x\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("continuing asks:" in f for f in failures), failures)
        self.assertFalse(any("item key at indent" in f for f in failures), failures)

    def test_a_digit_led_key_shaped_line_below_item_paragraph_takes_criterion_36_not_criterion_20(self):
        """Criterion 20(b), position 3: the same line as the first
        continuation of `item: >`, one indent short of six, takes criterion
        36's continuation-line message, not criterion 20's or criterion
        37's unrecognized-line message: `in_item` routes any deeper-than-4
        line to the paragraph check regardless of what it looks like."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "     2026-note: x\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("continuation line at indent 5" in f for f in failures), failures)
        self.assertFalse(any("item key at indent" in f for f in failures), failures)
        self.assertFalse(any("unrecognized line" in f for f in failures), failures)

    # ---- ordering and duplication --------------------------------------------

    def test_keys_out_of_schema_order_is_refused_naming_the_early_key(self):
        """Criterion 21: checked before opened, the exact regression case
        that used to compare against the previous item's date or nothing."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    checked: 2026-01-01\n"
            "    opened: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("'checked' before 'opened'" in f for f in failures), failures)

    def test_missing_key_is_refused_naming_it(self):
        """Criterion 22: an item with no asks: line at all."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("no `asks:` line" in f for f in failures), failures)

    def test_repeated_key_in_one_item_is_refused_naming_it(self):
        """Criterion 22: opened: written twice in the same item."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    opened: 2026-01-02\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("'opened' twice in one item" in f for f in failures), failures)

    def test_entry_opening_with_a_key_other_than_id_is_refused_naming_the_key(self):
        """Criterion 19: the first key on an entry must be id."""
        root = self._root()
        body = (
            "  - opened: 2026-01-01\n"
            "    id: sample-item\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("opening with key 'opened'" in f for f in failures), failures)

    def test_quoted_key_is_refused_by_name(self):
        """Criterion 24: a quoted key like "id": x is refused."""
        root = self._root()
        body = (
            "  - \"id\": sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("quoted key" in f for f in failures), failures)

    def test_unknown_key_is_refused_naming_it(self):
        """A key outside the schema's six is refused, naming the key found."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    extra: nope\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("unknown key 'extra'" in f for f in failures), failures)

    def test_duplicate_id_within_one_file_is_refused_naming_the_id(self):
        """Criterion 26: two items sharing an id, unique-in-file rule."""
        root = self._root()
        body = item_block(id_="same-id") + item_block(id_="same-id")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("id 'same-id' twice in one file" in f for f in failures), failures)
        self.assertEqual(len(items), 1)

    def test_key_with_no_space_after_the_colon_is_refused(self):
        """`opened:2026-01-01` with no space after the colon is refused
        rather than read as the literal value with no fix stated."""
        root = self._root()
        body = item_block().replace("opened: 2026-01-01", "opened:2026-01-01")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("key 'opened' with no space after the colon" in f for f in failures), failures)
        self.assertEqual(items, [])

    # ---- the id pattern (criterion 25) ---------------------------------------

    def test_quoted_id_is_refused_naming_the_whole_quoted_value(self):
        """Criterion 25: a quoted id fails the lowercase-hyphen pattern, so
        the whole quoted token, quotes included, is named and refused."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(id_='"kebab-case"')))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("id '\"kebab-case\"' is not lowercase" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_multi_word_id_is_refused_naming_the_whole_value(self):
        """Criterion 25: id: two words used to silently become 'two' under
        the old $3 read. The whole value is refused, never truncated."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(id_="two words")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("id 'two words' is not lowercase" in f for f in failures), failures)
        self.assertEqual(items, [])

    # ---- dates ---------------------------------------------------------------

    def test_date_that_is_not_a_date_is_refused(self):
        """Criterion 27: a value with no date shape at all."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="not-a-date")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("opened 'not-a-date' is not a date" in f for f in failures), failures)

    def test_unpadded_date_is_refused(self):
        """Criterion 27: 2026-9-1 breaks the fixed-width string comparison used
        elsewhere; the parser refuses it rather than silently sorting it wrong."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-9-1")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("opened '2026-9-1' is not a date" in f for f in failures), failures)

    def test_impossible_calendar_date_is_refused(self):
        """Criterion 27: 2026-02-30 matches the digit shape but not a real date."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-02-30")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("not a real calendar date" in f for f in failures), failures)

    def test_quoted_date_is_refused(self):
        """Criterion 27: a quoted date sorts before every digit in a naive
        string comparison, which is why the parser refuses it outright."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(checked='"2026-01-01"')))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("is not a date" in f for f in failures), failures)

    def test_checked_before_opened_is_refused_naming_both(self):
        """Criterion 28: checked earlier than opened makes no sense."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-01-10", checked="2026-01-01")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("checked 2026-01-01 before opened 2026-01-10" in f for f in failures), failures)

    def test_opened_date_after_the_run_date_is_refused(self):
        """Criterion 29: a future date, deterministic via --today equivalent."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-12-01", checked="2026-12-01")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"], today=TODAY)
        self.assertTrue(any("after the run date 2026-09-11" in f for f in failures), failures)

    def test_checked_date_after_the_run_date_is_refused(self):
        """Criterion 29: same rule applies to checked, not only opened. A
        future checked date would keep an item out of the stale list forever."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-01-01", checked="2026-12-01")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"], today=TODAY)
        self.assertTrue(any("checked 2026-12-01 after the run date 2026-09-11" in f for f in failures), failures)

    # ---- triggers refusals -----------------------------------------------

    def test_triggers_as_an_indented_block_list_is_refused(self):
        """Criterion 30: the shape that used to drop the whole item silently."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers:\n"
            "      - first trigger\n"
            "      - second trigger\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("triggers: as a block list" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_triggers_flow_sequence_with_bracket_on_a_later_line_is_refused(self):
        """Criterion 31, shape (b): the closing ] on its own indented line."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [first trigger,\n"
            "      second trigger]\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("runs past its own line" in f for f in failures), failures)

    def test_triggers_flow_sequence_continued_on_an_indented_line_is_refused(self):
        """Criterion 31, shape (a): a complete [..] followed by a stray
        continuation line, which is not a key, must not be half-parsed."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [first trigger]\n"
            "      stray continuation text\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("continuing triggers:" in f for f in failures), failures)

    def test_triggers_empty_flow_list_is_refused(self):
        """Criterion 32: triggers: [] loses the whole purpose of the field."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(triggers="[]")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("empty list" in f for f in failures), failures)

    def test_triggers_with_nothing_after_the_colon_is_refused(self):
        """Criterion 32: triggers: with no value at all, same rule as []."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers:\n"
            "    asks: \"\"\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("triggers: with nothing after it" in f for f in failures), failures)

    def test_triggers_not_starting_with_a_bracket_is_refused(self):
        """triggers: bare text with no bracket at all is refused, not read as
        one giant single trigger."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(triggers="a trigger, another")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("not a bracketed list" in f for f in failures), failures)

    # ---- asks refusals -------------------------------------------------------

    def test_asks_continued_on_an_indented_line_is_refused(self):
        """Criterion 33: asks: text that spills onto a second, deeper line."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: Part of the question\n"
            "      continues here.\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("continuing asks:" in f for f in failures), failures)

    def test_asks_as_a_block_scalar_is_refused(self):
        """Criterion 33: asks: > is a block scalar header, not an inline value.

        No continuation line follows asks: here on purpose: one does exist
        (see the next test) and the runs-on check for a continued asks: value
        fires first, which is a separate, correctly distinct refusal."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: >\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("block scalar" in f for f in failures), failures)

    def test_bare_asks_with_nothing_after_the_colon_is_refused(self):
        """asks: with no value at all, distinct from asks: "" which means
        empty on purpose. An item with a silently-missing question is not
        the same state as one that declares it owes none."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks:\n"
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("asks: with nothing after it" in f for f in failures), failures)
        self.assertEqual(items, [])

    # ---- item header refusals -------------------------------------------------

    def test_item_header_variants_other_than_gt_are_each_refused(self):
        """Criterion 34: |, >-, |-, >+, |+ and >2 are each tested."""
        for header in (">", "|", ">-", "|-", ">+", "|+", ">2"):
            root = self._root()
            body = (
                "  - id: sample-item\n"
                "    opened: 2026-01-01\n"
                "    checked: 2026-01-01\n"
                "    triggers: [a trigger]\n"
                "    asks: \"\"\n"
                f"    item: {header}\n"
                "      Text.\n"
            )
            self._write(root, "a.md", wrapped(body))
            failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
            if header == ">":
                self.assertEqual(failures, [], header)
            else:
                self.assertTrue(any("header" in f for f in failures), (header, failures))

    def test_item_with_text_on_the_keys_own_line_is_refused_as_inline(self):
        """Criterion 35: item: some text, no > header at all."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "    asks: \"\"\n"
            "    item: The paragraph is written right here.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("text on the key's own line" in f for f in failures), failures)

    # ---- unrecognized lines ----------------------------------------------

    def test_line_matching_no_accepted_pattern_is_refused_naming_line_and_text(self):
        """Criterion 37: gibberish inside the block, at the key indent, no colon."""
        root = self._root()
        body = item_block().replace("    triggers: [a trigger]\n", "    triggers: [a trigger]\n    not a key line at all\n")
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("unrecognized line" in f and "not a key line at all" in f for f in failures), failures)

    def test_line_before_the_first_item_is_refused(self):
        """Text inside the open_items: block before any `-` opens an entry."""
        root = self._root()
        self._write(root, "a.md", "---\nopen_items:\n  stray text here\n" + item_block() + "---\n")
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("before the first item" in f for f in failures), failures)

    # ---- the unquoted hash (criterion 38, option (c) as implemented) --------

    def test_unquoted_hash_preceded_by_space_in_asks_is_refused_by_name(self):
        """Criterion 38: skills/sage-brand-guidelines/SKILL.md line 41's real
        shape. YAML would read ' #' as a comment start and truncate silently;
        the script refuses it by name instead."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(
            asks="Should the accent hex move from #D94F1A to roughly #B03B0A?")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("unquoted ` #`" in f for f in failures), failures)
        self.assertEqual(items, [])

    def test_quoted_value_carries_the_unquoted_hash_text_through_whole(self):
        """Criterion 38: the fix for the real file above, quoting the value,
        must carry the entire question, hash included, not five words of it."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(
            asks='"Should the accent hex move from #D94F1A to roughly #B03B0A?"')))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertEqual(failures, [])
        self.assertEqual(
            items[0]["asks"],
            "Should the accent hex move from #D94F1A to roughly #B03B0A?",
        )

    def test_unquoted_hash_in_a_triggers_entry_is_also_refused(self):
        """The same rule applies wherever an inline value is read, not just asks."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(triggers="[a phrase with a #hash, plain]")))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("triggers: entry that carries an unquoted ` #`" in f for f in failures), failures)

    def test_unbalanced_quote_in_an_inline_value_is_refused(self):
        """A quote around only part of the value, never silently half-stripped."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(asks='"Half a quote here')))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("unbalanced quote" in f for f in failures), failures)

    # ---- regression: the two named defects -----------------------------

    def test_crlf_is_visible_because_the_file_is_opened_with_no_newline_translation(self):
        """The first named defect: universal newlines would turn \\r\\n into
        \\n on the way in, and the CRLF check could never fire. This proves
        the file is opened the way that keeps \\r visible, on a file that
        would otherwise parse clean."""
        root = self._root()
        good = wrapped(item_block())
        crlf = good.replace("\n", "\r\n")
        path = self._write_bytes(root, "a.md", crlf.encode("utf-8"))
        with path.open(encoding="utf-8", newline="") as handle:
            text = handle.read()
        self.assertIn("\r", text)
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("CRLF" in f for f in failures), failures)

    def test_key_at_wrong_indent_after_a_valid_triggers_line_is_reported_as_a_bad_indent_not_a_triggers_overrun(self):
        """The second named defect: a key at the wrong indent following
        triggers: used to be reported as triggers: running past its own line.
        A key-shaped line is never mistaken for a triggers: continuation."""
        root = self._root()
        body = (
            "  - id: sample-item\n"
            "    opened: 2026-01-01\n"
            "    checked: 2026-01-01\n"
            "    triggers: [a trigger]\n"
            "     asks: \"\"\n"  # five spaces, one off from four
            "    item: >\n"
            "      Text.\n"
        )
        self._write(root, "a.md", wrapped(body))
        failures, questions, due, items, files, declaring = self._run(root, ["a.md"])
        self.assertTrue(any("item key at indent 5" in f for f in failures), failures)
        self.assertFalse(any("triggers:" in f and "runs past" in f for f in failures), failures)

    # ---- a read that yields nothing is a failure (39-46) --------------------

    def test_three_counts_print_on_their_own_lines(self):
        """Criterion 42: files read, files declaring, items parsed."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block()))
        self._write(root, "b.md", "---\nname: x\n---\nBody.\n")
        code, out = self._quiet_main(["prog", "--root", str(root), str(root / "a.md"), str(root / "b.md")])
        self.assertIn("2 file(s) read", out)
        self.assertIn("1 file(s) declaring open_items:", out)
        self.assertIn("1 item(s)", out)

    def test_three_output_classes_are_each_named_in_output(self):
        """Criterion 44: failure, question and due item each print, labelled.

        Corrected: the old fixture produced 0 failures and 0 questions, so
        `assertIn("failure(s)", out)` only ever matched the always-printed
        "0 failure(s)" count line, and nothing asserted the "Questions."
        label at all, so deleting that print survived the suite. The fixture
        now produces one real failure, one real question and one real due
        item, and all three labels are asserted."""
        root = self._root()
        self._write(root, "bad.md", "---\nopen_items:\n  - id: x\n")  # unterminated frontmatter: 1 failure
        self._write(root, "stray.md", "# doc\n\nopen_items:\n  - id: x\n")  # column 0, outside frontmatter: 1 question
        self._write(root, "old.md", wrapped(item_block(opened="2026-01-01", checked="2026-01-01")))  # 1 due item
        code, out = self._quiet_main([
            "prog", "--root", str(root), "--today", "2026-09-11", "--stale-days", "14",
            str(root / "bad.md"), str(root / "stray.md"), str(root / "old.md"),
        ])
        self.assertIn("1 failure(s)", out)
        self.assertIn("Questions.", out)
        self.assertIn("Due.", out)

    def test_exit_code_zero_failures_zero_questions(self):
        """Criterion 44: the arithmetic baseline, a clean run."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block()))
        code, out = self._quiet_main(["prog", "--root", str(root), str(root / "a.md")])
        self.assertEqual(code, 0)

    def test_exit_code_one_failure_only(self):
        """Criterion 44: one failure, zero questions.

        Corrected: the old fixture, a file with no frontmatter and no
        open_items: anywhere, produces 0 failures and 1 question (criterion
        43's "no file declares" question), so the test passed on the
        question and asserted nothing about a failure. The fixture now has a
        real failure (unterminated frontmatter) plus a second file that
        declares, so criterion 43's question does not also fire."""
        root = self._root()
        self._write(root, "bad.md", "---\nopen_items:\n  - id: x\n")
        self._write(root, "ok.md", wrapped(item_block()))
        code, out = self._quiet_main(["prog", "--root", str(root), str(root / "bad.md"), str(root / "ok.md")])
        self.assertEqual(code, 1)

    def test_exit_code_one_question_only(self):
        """Criterion 44: zero failures, one question (the stray open_items:
        case). A second, real-item file keeps `declaring` above zero, so the
        whole-run-empty question of criterion 43 does not also fire and
        double the count."""
        root = self._root()
        self._write(root, "a.md", "# doc\n\nopen_items:\n  - id: x\n")
        self._write(root, "b.md", wrapped(item_block()))
        code, out = self._quiet_main(["prog", "--root", str(root), str(root / "a.md"), str(root / "b.md")])
        self.assertEqual(code, 1)

    def test_exit_code_one_failure_and_one_question_together(self):
        """Criterion 44: failures plus questions, both present, sums to two.
        Uses the declares-and-yields-no-item failure, which does not depend
        on the no-frontmatter path (see the criterion 12 finding below)."""
        root = self._root()
        self._write(root, "bad.md", "---\nopen_items:\n---\n")
        self._write(root, "stray.md", "# doc\n\nopen_items:\n  - id: x\n")
        self._write(root, "ok.md", wrapped(item_block()))
        code, out = self._quiet_main([
            "prog", "--root", str(root), str(root / "bad.md"), str(root / "stray.md"), str(root / "ok.md"),
        ])
        self.assertEqual(code, 2)

    def test_exit_code_caps_at_125_past_the_limit(self):
        """Criterion 44: the count caps at 125 even with far more failures.

        Each fixture declares open_items: and yields no item, a failure that
        does not depend on the no-frontmatter path (see the criterion 12
        finding below)."""
        root = self._root()
        for i in range(130):
            self._write(root, f"bad-{i}.md", "---\nopen_items:\n---\n")
        paths = [str(root / f"bad-{i}.md") for i in range(130)]
        code, out = self._quiet_main(["prog", "--root", str(root)] + paths)
        self.assertEqual(code, 125)
        self.assertIn("130 failure(s)", out)

    def test_a_due_item_never_affects_the_exit_code(self):
        """Criterion 44: due items are reading-pass findings only."""
        root = self._root()
        self._write(root, "old.md", wrapped(item_block(opened="2026-01-01", checked="2026-01-01")))
        code, out = self._quiet_main([
            "prog", "--root", str(root), "--today", "2026-09-11", "--stale-days", "14",
            str(root / "old.md"),
        ])
        self.assertIn("1 due item(s)", out)
        self.assertEqual(code, 0)

    def test_due_item_reported_when_checked_older_than_the_cutoff(self):
        """Criterion 45: checked older than --stale-days before --today."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-01-01", checked="2026-01-01")))
        failures, questions, due, items, files, declaring = self._run(
            root, ["a.md"], today=datetime.date(2026, 9, 11), stale_days=14)
        self.assertEqual(len(due), 1)
        self.assertIn("a.md", due[0])
        self.assertIn("sample-item", due[0])

    def test_item_checked_inside_the_window_is_not_due(self):
        """Criterion 45, the boundary the other side: checked recently enough."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-09-01", checked="2026-09-01")))
        failures, questions, due, items, files, declaring = self._run(
            root, ["a.md"], today=datetime.date(2026, 9, 11), stale_days=14)
        self.assertEqual(due, [])

    def test_cutoff_is_computed_deterministically_from_today_and_stale_days(self):
        """Criterion 46: no shell `date -v` involved; passing --today and
        --stale-days makes the cutoff exact and reproducible."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-08-01", checked="2026-08-20")))
        failures, q, due, items, files, declaring = self._run(
            root, ["a.md"], today=datetime.date(2026, 9, 11), stale_days=14)
        self.assertEqual(len(due), 1)
        self.assertIn("older than 2026-08-28", due[0])

    # ---- the interface: --today, --stale-days, --findings-only --------------

    def test_cli_today_flag_makes_a_future_date_check_deterministic(self):
        """Criterion 48: --today drives criterion 29's check through the CLI."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(opened="2026-09-20", checked="2026-09-20")))
        code, out = self._quiet_main(["prog", "--root", str(root), "--today", "2026-09-11", str(root / "a.md")])
        self.assertIn("after the run date 2026-09-11", out)

    def test_cli_today_that_is_not_a_date_is_rejected(self):
        """The CLI's own validation of --today, not delegated to a traceback."""
        code, out = self._quiet_main(["prog", "--today", "not-a-date"])
        self.assertEqual(code, 1)
        self.assertIn("is not a date", out)

    def test_cli_negative_stale_days_is_rejected(self):
        """--stale-days must be a whole number of days, never negative."""
        code, out = self._quiet_main(["prog", "--stale-days", "-1"])
        self.assertEqual(code, 1)
        self.assertIn("negative", out)

    def test_findings_only_suppresses_the_item_listing(self):
        """Criterion 47/50: --findings-only drops the listing but keeps counts."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(asks="A real question here.")))
        code, out = self._quiet_main(["prog", "--root", str(root), "--findings-only", str(root / "a.md")])
        self.assertNotIn("asks set", out)
        self.assertIn("1 item(s)", out)

    def test_listing_shows_asks_state_as_set_or_empty(self):
        """Criterion 49: the asks state, new support wiki-open-items needs."""
        root = self._root()
        self._write(root, "with-ask.md", wrapped(item_block(id_="has-ask", asks="A real question.")))
        self._write(root, "no-ask.md", wrapped(item_block(id_="no-ask", asks='""')))
        code, out = self._quiet_main(["prog", "--root", str(root), str(root / "with-ask.md"), str(root / "no-ask.md")])
        self.assertIn("has-ask", out)
        self.assertIn("asks set", out)
        self.assertIn("no-ask", out)
        self.assertIn("asks empty", out)

    def test_paragraph_text_is_validated_but_never_printed(self):
        """Criterion 50: the listing carries no item paragraph text."""
        root = self._root()
        self._write(root, "a.md", wrapped(item_block(para="This exact sentence must never print.")))
        code, out = self._quiet_main(["prog", "--root", str(root), str(root / "a.md")])
        self.assertNotIn("This exact sentence must never print.", out)

    # ---- standard library only (criterion 51) --------------------------------

    def test_script_imports_nothing_outside_the_standard_library(self):
        """Criterion 51: every top-level import resolves inside the stdlib."""
        import ast
        import sysconfig
        # Both sides resolved: a Homebrew Python reports the stdlib through a
        # symlinked prefix while find_spec() returns the real path.
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

    # ---- criterion 53's note: run against the real tree, no count asserted --

    def test_real_tree_run_does_not_raise_and_reads_the_files_the_list_names(self):
        """Criterion 53's caveat: item counts on the live tree go stale as
        items close (roots/AGENTS.md's item closed after this criterion was
        written, dropping the live count from 10 across 3 files to 9 across
        2), so nothing here asserts a count against today's content. This
        asserts only a fact about the script: it does not raise, and it reads
        exactly the files scripts/open-items-files.txt names, no more, no
        fewer."""
        list_path = CONTAINER_ROOT / "scripts" / "open-items-files.txt"
        expected = []
        for line in list_path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                expected.append(line)
        failures, questions, due, items, files, declaring = coi.run(CONTAINER_ROOT)
        self.assertEqual(len(files), len(expected))

    def test_real_tree_every_declaring_file_yields_at_least_one_item(self):
        """Criterion 53(b): every checked file that declares open_items: in
        its frontmatter yields at least one item -- criterion 41 held on the
        live tree, so the count of files carrying an item equals the count
        of files that declare."""
        failures, questions, due, items, files, declaring = coi.run(CONTAINER_ROOT)
        self.assertGreater(declaring, 0)
        files_with_items = {item["file"] for item in items}
        self.assertEqual(len(files_with_items), declaring)

    def test_real_tree_item_count_per_file_matches_the_dash_id_lines_between_the_first_two_dashes(self):
        """Criterion 53(c): the number of items parsed in a file equals the
        number of lines matching `^  - id: ` between that file's first two
        --- lines, where those two lines are the frontmatter delimiters: a
        first line that is exactly --- and the next line after it that is
        exactly ---, per the schema's own definition of frontmatter. The
        expected count is derived from each file's own content here, never
        pinned as a literal, so this follows the tree as items open and
        close. SPEC.md is deliberately a case with no expected items: it
        carries no frontmatter, so its first-line test fails and its
        fenced ```yaml example, which happens to hold the only literal ---
        lines anywhere in the file, contributes nothing."""
        failures, questions, due, items, files, declaring = coi.run(CONTAINER_ROOT)
        counted = {}
        for item in items:
            counted[item["file"]] = counted.get(item["file"], 0) + 1
        id_line = re.compile(r"^  - id: ")
        for path in files:
            rel = coi.shown(path, CONTAINER_ROOT)
            lines = path.read_text(encoding="utf-8").splitlines()
            expected = 0
            if lines and lines[0] == "---":
                for i in range(1, len(lines)):
                    if lines[i] == "---":
                        expected = sum(1 for line in lines[1:i] if id_line.match(line))
                        break
            self.assertEqual(counted.get(rel, 0), expected, rel)

    def test_real_tree_ids_match_the_pattern_and_are_unique_per_file(self):
        """Criterion 53(d): every id parsed on the live tree matches
        criterion 3's lowercase-hyphen pattern and is unique within its
        file."""
        failures, questions, due, items, files, declaring = coi.run(CONTAINER_ROOT)
        seen = set()
        for item in items:
            self.assertRegex(item["id"], coi.ID_RE.pattern)
            key = (item["file"], item["id"])
            self.assertNotIn(key, seen, key)
            seen.add(key)

    def test_real_tree_reports_no_failure_and_no_question(self):
        """The live tree is clean, and clean now means exit 0. Before the fence
        tracker the two documentation examples each printed a question, so a
        correct tree exited 2 and the script could never be a commit gate.
        Zero is the state, not a count that goes stale: a question here means a
        context file carries an `open_items:` at column 0 outside frontmatter and
        outside a fenced block, which is the case worth blocking on."""
        failures, questions, due, items, files, declaring = coi.run(CONTAINER_ROOT)
        self.assertEqual(failures, [])
        self.assertEqual(questions, [])

    # ---- light integration checks on the two skills (read-only) -------------

    def test_no_awk_program_reads_open_items_in_either_skill(self):
        """Criterion 57: the four inline awk programs over open_items are
        gone; the one over ## Open questions in wiki-verify is out of scope
        and named separately, so it must not trip this check."""
        for rel in ("wiki/skills/wiki-open-items/SKILL.md", "wiki/skills/wiki-verify/SKILL.md"):
            text = (CONTAINER_ROOT / rel).read_text(encoding="utf-8")
            for line in text.splitlines():
                if "open_items" in line:
                    self.assertNotIn("awk", line, f"{rel}: {line!r}")

    def test_scripts_readme_documents_check_open_items(self):
        """Criterion 60: scripts/README.md carries a row and a section for
        check-open-items.py. Met 2026-09-11 per SPEC.md; this is the
        regression guard."""
        readme = (CONTAINER_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
        self.assertIn("check-open-items.py", readme)


if __name__ == "__main__":
    unittest.main()
