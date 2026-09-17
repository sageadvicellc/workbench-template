#!/usr/bin/env python3
"""Check every skill file for the frontmatter a harness needs.

A harness is the program that runs the agent loop and reads these files. It
skips a malformed skill file in silence, so this is the only thing that
reports one.

Run from the workbench root:

    python3 scripts/check-skills.py

An optional argument checks a different tree, which is what the tests use:

    python3 scripts/check-skills.py /path/to/a/fixture/root

Skills, every directory directly under `wiki/skills/`:

1. A `SKILL.md` that sits deeper than `wiki/skills/<dir>/SKILL.md` is
   reported. A skill nested one level too deep is not discovered, and nothing
   else says so.
2. A directory with no skill file of its own is reported. Dot directories are
   not.
3. `name` matches the directory, unless the directory is in THIRD_PARTY_SKILLS.
   An installed skill may legitimately carry a name that differs from the
   directory it was installed into.
4. `name` is lowercase letters, digits and single hyphens, and at most 64
   characters. Both rules come from the Agent Skills specification and both run
   on exempt skills.
5. `description` is not empty. It is what the model routes on.

The tree itself:

6. `wiki/skills/` exists at the checked root. Without this the script reports a
   clean tree when it is looking at the wrong directory, which as a commit gate
   is the worst thing it could do.

Frontmatter is read only when `---` is the first line of the file. A leading
blank line or a byte order mark turns the whole file into body text, and both
are reported. A closing `---` at the end of the file with no trailing newline
is fine.

The exit code is the number of failures, capped at 125, so this works as a
pre-commit hook with no wrapper.

Every path that cannot be read is reported as a failure naming the path. The
script never raises on a tree shape.

Standard library only.
"""

import re
import sys
from pathlib import Path

# Where the skills live, relative to the checked root.
SKILLS_DIR = "wiki/skills"

# Directories under wiki/skills/ holding a skill somebody else wrote, whose
# `name` does not match the directory it was installed into.
#
# This is an exemption from a published standard, not from a house convention.
# The Agent Skills specification, https://agentskills.io/specification, read
# 2026-09-11, states the `name` field "Must match the parent directory name".
# A skill listed here does not conform. A harness invokes an installed skill
# by its directory name, so it still loads, but the file is non-conforming and
# the exemption is a decision to tolerate that in somebody else's file rather
# than a statement that the rule does not apply.
THIRD_PARTY_SKILLS = set()

# Agent Skills specification, https://agentskills.io/specification, read
# 2026-09-11: 1 to 64 characters, lowercase alphanumeric and hyphens, no
# leading or trailing hyphen, no consecutive hyphens. The pattern covers every
# rule except the length, which is checked separately.
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX = 64
# The closing fence may end the file, so the trailing newline is optional. A
# file whose last byte is the final `-` is valid and must not be reported.
FRONT_RE = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.S)
SKILL_FILE = "SKILL.md"
BOM = "﻿"


def parse(path, rel, failures):
    """Top-level frontmatter scalars of one file, or None after saying why not.

    A key whose value runs past its own line is not read. Nothing this script
    checks is written that way, and a value guessed out of a shape nobody
    declared is worse than a value left unread.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"{rel}: cannot be read, {type(exc).__name__}")
        return None
    except UnicodeDecodeError:
        failures.append(f"{rel}: is not UTF-8 text")
        return None
    if text.startswith(BOM):
        failures.append(f"{rel}: starts with a byte order mark, so --- is not the first thing in it")
        return None
    match = FRONT_RE.match(text)
    if not match:
        failures.append(f"{rel}: no frontmatter, or --- is not the first line")
        return None
    fields = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def skill_file(directory):
    """Return (path, problem) for the SKILL.md directly inside a directory.

    A name match alone is not enough: the entry may be a directory or a
    dangling symlink, and the caller is about to read it. Absent and present
    but unreadable are different faults and get different messages.
    """
    if not directory.is_dir():
        return None, f"no {SKILL_FILE}"
    named = [e for e in directory.iterdir() if e.name == SKILL_FILE]
    if not named:
        return None, f"no {SKILL_FILE}"
    if not named[0].is_file():
        return None, f"{SKILL_FILE} is not a readable file"
    return named[0], None


def check_skills(root, failures):
    skills_dir = root / SKILLS_DIR
    if not skills_dir.is_dir():
        failures.append(f"{SKILLS_DIR}: no such directory at the checked root")
        return
    for directory in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        if directory.name.startswith("."):
            continue
        rel = directory.relative_to(root).as_posix()

        # A skill file below <dir>/ is not discovered, whatever it says.
        nested = sorted(
            p for p in directory.rglob(SKILL_FILE)
            if p.name == SKILL_FILE and p.parent != directory
        )
        for path in nested:
            failures.append(
                f"{path.relative_to(root).as_posix()}: nested below "
                f"{SKILLS_DIR}/{directory.name}/, so this skill is not discovered"
            )

        path, problem = skill_file(directory)
        if path is None:
            if not nested:
                failures.append(f"{rel}: {problem}")
            continue

        rel_file = path.relative_to(root).as_posix()
        fields = parse(path, rel_file, failures)
        if fields is None:
            continue
        name = fields.get("name", "")
        if name != directory.name and directory.name not in THIRD_PARTY_SKILLS:
            failures.append(f"{rel_file}: name '{name}' does not match directory")
        if not NAME_RE.match(name):
            failures.append(f"{rel_file}: name '{name}' is not lowercase-hyphen")
        if len(name) > NAME_MAX:
            failures.append(f"{rel_file}: name is {len(name)} characters, over the {NAME_MAX} the spec allows")
        if not fields.get("description"):
            failures.append(f"{rel_file}: no description")


def run(root):
    """Check one tree. Returns the failure lines, sorted."""
    root = Path(root)
    failures = []
    check_skills(root, failures)
    return sorted(failures)


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    failures = run(root)
    for line in failures:
        print(line)
    print(f"{len(failures)} failure(s)")
    return min(len(failures), 125)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
