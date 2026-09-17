---
type: index
updated: 2026-09-17
---

# scripts

The flat home for everything executable that is not part of a skill or a
project repo.

A harness is the program that runs the agent loop and reads these files. No
script here names one. A path, a filename, or a setting that belongs to one
harness lives in that harness's adapter, under `adapters/`.

`central-context/` holds no code, by rule. When a check there needs to run
rather than be read, it lives here and `central-context/AGENTS.md` names it by
path.

A script that belongs to one skill stays with that skill, under
`wiki/skills/<name>/`. A script that belongs to one project stays in that
project's repo. Everything else is here.

| Script | Does | Run from |
|---|---|---|
| `check-skills.py` | Checks skill frontmatter under `wiki/skills/` | The workbench root: `python3 scripts/check-skills.py` |
| `check-open-items.py` | Checks the `open_items` frontmatter of the context files | The workbench root: `python3 scripts/check-open-items.py` |
| `open-items-files.txt` | Data, not a script. The context files `check-open-items.py` reads by default | Read by `check-open-items.py` |
| `sync-harness.py` | Generates, per adapter manifest, the MCP tables a harness reads in its own format, from `.mcp.json` | The workbench root: `python3 scripts/sync-harness.py`, or `--check` to report and write nothing |
| `check-harness.py` | Proves the wiring: every declared symlink, every skill reachable through it, every generated file current, no harness named in the neutral core, and the entrypoint under its size cap | The workbench root: `python3 scripts/check-harness.py` |

## check-skills.py

A harness skips a malformed skill file in silence, so this is the only thing
that reports one.

It checks every directory directly under `wiki/skills/`: that a `SKILL.md`
sits directly under `wiki/skills/<dir>/` and not deeper, that no skill
directory is empty, that `name` matches the directory and is lowercase-hyphen
and at most 64 characters, and that `description` is not empty. It also
reports a missing `wiki/skills/` at the checked root, so a run against the
wrong directory never reports a clean tree.

Every finding is a failure, and every failure is a defect. Fix the file. The
exit code is the failure count, capped at 125, which makes the script usable
as a pre-commit hook with no wrapper. Nothing calls it automatically yet.
Wiring it into one is a decision for this workbench; open an item in
`AGENTS.md` if you want it tracked.

### Exempting somebody else's skill

`THIRD_PARTY_SKILLS` in the script exempts an installed skill whose `name`
differs from the directory it was installed into. The set ships empty, so
nothing is exempt today. That is an exemption from a published standard, not
from a house convention: the Agent Skills specification,
`https://agentskills.io/specification`, read 2026-09-11, states the `name`
field "Must match the parent directory name". A listed skill does not conform.
A harness invokes an installed skill by its directory name, so it still loads,
and the exemption is a decision to tolerate a non-conforming file somebody else
wrote. Everything not listed there is checked, so a skill you wrote is never
skipped by forgetting to register it.

The same specification sets the other name rules the script enforces: 1 to 64
characters, lowercase alphanumeric and hyphens, no leading or trailing hyphen,
no consecutive hyphens. It also publishes a validator, `skills-ref validate`,
which checks a single skill and not the nesting or the tree shape this script
covers.

## check-open-items.py

An open item is a question nobody has settled, written into the `open_items`
frontmatter of a context file. This script is the one reader of that block.

One written form is accepted. It is the example block in the `Open items schema`
section of `central-context/AGENTS.md`, which is the authority on the six fields
and on what each one holds. `open_items:` sits at column 0 inside frontmatter,
an item opens at two spaces with `- id:`, the five other keys each sit on their
own line at four spaces in the schema's order, and the `item: >` paragraph sits
at six. Every other form is refused by name, never parsed and never guessed at.
A refusal names the path, the line, the shape found, and the edit that fixes it.
A refused item is dropped whole, so no file is ever half-read while it appears
read.

Three things it reports separately:

- **A failure** is a defect. A refused shape, a path it cannot read, or a file
  that declares `open_items:` and yields no item. Reading nothing is never a
  pass.
- **A question** blocks and says nothing about the file being wrong. There are
  two: no file read declares `open_items:` at all, which almost always means the
  paths are wrong, and an `open_items:` at column 0 outside frontmatter and
  outside a fenced code block, which the script does not read and cannot tell
  from a block somebody wrote in the wrong place.
- **A due item** is one whose `checked` date is older than the cutoff. Nobody has
  tested that claim since the date shown. `wiki-verify` re-tests it in a reading
  pass, so a due item never affects the exit code.

The exit code is the failures plus the questions, capped at 125, so it can run
as a pre-commit hook with no wrapper. Nothing calls it automatically yet.

**On a clean tree it reports 0 failures and 0 questions, and it exits 0.** Any
finding on a tree nobody has just edited is worth reading.

The script ignores every line inside a fenced code block. A fenced example is
documentation, never a declaration. A fence that opens and never closes is a
failure naming the line it opened on, because every line below an open fence
is unread.

With no path argument the script reads the file list at
`scripts/open-items-files.txt`, one path per line. **An item in a file that list
does not name is invisible.** When you write an item into a file the list does
not name, add the line in the same commit. A listed path that no longer exists
is a failure. A path argument checks something else instead, and a directory
argument checks every `*.md` file below it. An entry below it that the
filesystem cannot describe, such as a broken symlink, is a failure too, and it
still counts as a file the run found.

Four options:

- `--findings-only` prints the findings and the counts, and holds back the item
  listing. Mechanical check 1 of `wiki/skills/wiki-verify/SKILL.md` calls the
  script this way.
- `--stale-days N` sets the due window, in days since `checked`. Default 14.
- `--today YYYY-MM-DD` sets the run date, for a test.
- `--root PATH` sets the path findings print relative to.

## sync-harness.py

Every path, format identifier and harness fact it uses comes from
`adapters/<id>/wiring.json`, so the script names no harness. A manifest's
`mcp` block names a format, the source `.mcp.json`, the path to write, and a
hand-edited head to put first. That is the only block it renders. The
generated files are committed. Run the script after any edit to `.mcp.json`,
or to a head file, and commit what it wrote.

`--check` writes nothing and exits 1 with one line per file that is missing or
differs from its source. Exit 2 is an input the script cannot use, named on
stderr: an unreadable manifest, a format nobody registered, or an MCP server
the target format cannot express. It refuses rather than approximates, because
a server rendered differently from its source is a server that works on one
harness and silently not the other.

## check-harness.py

The one command that says whether a clone is wired. One line per failure,
then `N failure(s)`, and the exit code is N capped at 125. It reads the same
manifests as `sync-harness.py`, so an adapter is checked the moment its
manifest exists.

The harness-name scan reads `adapters/harness-names.txt`, strips every
`adapters/<id>/...` path token from a line, and reports every remaining match
in the nine permitted paths of the neutral core, `wiki/` among them, so the
pack's skills are scanned too. Zero on a clean tree is the right answer: every
sentence in the core that reaches an adapter carries a path and no harness
name. A plain file where a symlink should be gets the Windows fix in its
message.

Reachability is proved per link: for any link whose destination holds
`<dir>/SKILL.md` files, each of those files must be readable through the link.
A link an adapter points at `wiki/skills` is proved the same way as one
pointed anywhere else.

It proves wiring, not behaviour. Whether a harness loads the entrypoint, loads
a skill, or completes a wiki operation is the acceptance test below, which does
not exist yet.

## Tests

`tests/` holds the tests for every script here, one file per script. Run them
from the workbench root with `python3 -m unittest discover -s scripts/tests`.
What each file covers is described in its script's module docstring and above.

## Not built yet

`harness-acceptance.py` does not exist on disk on 2026-09-12, so this file does
not say what it does. Add its table row when it lands, written from the script
itself.

One thing about the acceptance test is settled and belongs here, because a
reader who runs it will see failures and wonder whether the suite is broken. It
proves a harness by checking three surfaces: the entrypoint loads without being
asked, one skill loads on demand, and one wiki operation completes end to end.
Two runs are expected to fail, and both exist to show that the test can detect
a broken tree.

1. Run against a harness identifier with no adapter installed, the test fails
   at the first surface and names the missing adapter.
2. Run with the skill discovery path removed, the test passes surfaces 1 and 3
   and fails surface 2.

The workbench's specification requires both to be stated as expected behaviour
in the test's own documentation.
