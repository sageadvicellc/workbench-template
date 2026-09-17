# Setup

Paste this whole file into your harness at the start of a session, running from
the workbench root, the first time you open a fresh clone. A harness is the
program that runs the agent loop and reads these files. This file is written for
the agent, not for you. You will be asked questions, and answering them is the
work.

Nothing below runs by itself. Do it in order, and stop where it says stop.

The template ships no permission rules, so every approval prompt you see while
this runs is your own machine asking you. Answering one, or writing a rule that
stops it asking, is yours to decide.

---

## What you are doing

This repo is a clone of a template. It carries a working structure, the five
wiki skills that run its knowledge base, and nothing else that does work. The
skills, roles, and pipelines that carry code, design, and research arrive as
packs and plugins the owner chooses here and installs on their own harness.
The template forces none of them.

Your job is to fill in this owner's identity and rules, to record which packs
and plugins they chose, and to leave nothing half-replaced. A workbench that
says "the owner" in four files and a real name in one is worse than one that
says "the owner" everywhere, because the reader cannot tell which is
deliberate.

The marker for everything unfilled is a line starting `> FILL:`, indented or
not. This is the check you run at the end:

```bash
grep -rn '^ *> FILL:' --include='*.md' .
```

An empty result is the finish line for stages 1 to 4. There are ten, all in
`AGENTS.md`.

---

## Stage 0: the harness, then the remote

**1. Prove the wiring.** Run this from the workbench root before anything
else:

```bash
python3 scripts/check-harness.py
```

`0 failure(s)` is the pass. The wiring for every supported harness is tracked
in git, so there is nothing to install: the symlinks each harness discovers
the tree through, and the files generated in each harness's own format, came
with the clone. A failure names the file and the fix. The one a fresh clone
can produce is a symlink checked out as a plain file, which happens on Windows
without `core.symlinks` and on any zip download; the message says what to run.
Do not continue with a failure standing.

**2. Which harness does the owner run?** The neutral core is what you cloned:
the entrypoint, the knowledge base, the wiki pack, the scripts, and this
file. It names no harness. Every harness-specific path lives in one thin
adapter under `adapters/`, and `adapters/README.md` is the index: it lists the
adapters that exist and carries the support matrix, one row per harness. Read
it with the owner. Take the current list from that index and not from this
file, because this file goes stale first.

Two outcomes, and each one is a legitimate end to this step:

- **An adapter exists for their harness.** Its `README.md` opens with the
  steps for this harness: how to install the wiki pack, how to install the
  packs chosen in step 3 below, how to start the session, and how to confirm
  the skills loaded. Walk them after step 3, so there is one install pass.
- **No adapter exists for their harness.** Adding one is one directory under
  `adapters/` with a manifest and a `README.md`, one row in the support
  matrix, and a run of `python3 scripts/sync-harness.py`, and
  `adapters/README.md` says how. Every path in it comes from that harness's
  own documentation, with the URL and the date you read it. Root rule 4 binds
  here.

Record the harness and the adapter path as the first item in this session's
report. Stage 5 logs it as a decision.

**3. Which packs and plugins do the work?** Nothing that does work ships in
this tree. Four questions, one at a time, each with named variants and never
a pick made for the owner. `README.md` under "Packs and plugins" lists one
practice's working set with its install commands, as an example to hold up
and not as a default to assume.

- **Code, and anything built.** Which plugin carries an idea to a draft pull
  request? Variants: the set in the README, another the owner names, or none
  because nobody builds software here. The answer goes into `AGENTS.md` under
  "How work runs" and into the two code rows of the routing table.
- **Anything a person looks at.** Which skills bind interface work and which
  bind client-facing copy? The answer goes into rule 3. "None yet" is an
  answer; the rule then stays with its marker deleted.
- **The writing standard.** Which skill carries rule 2, and from where? The
  answer goes into rule 2. If none, delete the marker and the plain-language
  rules stand on their own.
- **Research.** Does a research team run here? If yes, which pack carries its
  roles and its operating procedure? The answer goes into "How work runs" and
  the research row of the routing table. If no, write "None" there and delete
  the research row.

For each pack the owner chooses, take the install command from the pack's own
README or from the harness's adapter `README.md`, run it on this machine, and
record the pack, its version, and the marketplace it came from in this
session's report. Stage 5 logs the set as a decision. The wiki pack is not a
question: install it, from this repo, unless the owner brings one that runs
the same five operations.

A plugin that loads into every session costs tokens in every session. Before
enabling one everywhere, measure it; the adapter's `README.md` says how on
its harness. Enabling per repository is the lever that prunes the cost.

**4. Point the remote somewhere else.** `origin` is the template. Anything
pushed there goes to the template, not to this workbench.

```bash
git remote -v
```

Ask the owner for their own repository URL, then:

```bash
git remote set-url origin <their-url>
git remote -v
```

If they have not made a repository yet, say so and leave `origin` alone rather
than inventing a URL. Record it in this session's report.

---

## Stage 1: the identity and the always-on rules

Open `AGENTS.md`. It has ten `> FILL:` blocks, and stage 0 step 3 has already
answered four of them: rule 2, rule 3, and the two under "How work runs".
Write those answers in now, then work the rest in order, asking one question
at a time and waiting for the answer. Do not guess an answer from context and
do not batch the questions into one wall.

**1. What this workbench is for.** One paragraph, in the owner's words. What
work happens here, and what it is not for.

**2. Identity.** Who the agent acts as, and who owns the decisions. Get the
owner's name and what the business or team is called.

Then decide with them how the name enters the files. Two variants:

- **Keep "the owner" everywhere.** Every wiki skill already reads this way.
  Nothing to change. Costs nothing, reads slightly impersonally.
- **Use their name everywhere.** One pass across `wiki/skills/`:
  `grep -rln 'the owner' --include='*.md' wiki/skills` finds every file.
  Reads better. It must be done in full or not at all. A pack installed from
  elsewhere is not in this tree and is not touched.

Name both. Do not pick.

Do the same for "the practice", which is the placeholder for the business name
and appears in the same files.

**3. Rule 2, the writing standard.** Write in the answer from stage 0 step 3:
the skill's name and the pack or marketplace it is installed from. If none,
delete the `> FILL:` marker and leave the plain-language rules standing. Say
which you did.

**4. Rule 3, interface and copy standards.** Same, from the same step. If
none, delete the marker and leave the rule standing.

**5. Rule 9, the names that never appear in client-facing material.** Ask
directly: are there employers, clients, or partners that must not be named in
anything a client sees? List them, or write "None" and leave the rule
standing. Several skills cite rule 9 by number, so the rule stays either way.

**6. "How work runs", the routing table, and the on-disk table.** Write the
code and research answers from stage 0 step 3 into "How work runs", replace
the three routing rows that point there with the chosen names, and add a row
per installed skill a session should route to by name. Add a row to the
on-disk table per project repo the owner intends to nest here. For each
project repo, also add its directory to `.gitignore` and to the `dirs` list
in `wiki/skills/wiki-verify/SKILL.md`.

---

## Stage 2: the packs load

Every pack chosen in stage 0 step 3 is installed by now. Prove it before
anything depends on it: open a session at the workbench root and confirm, the
way the adapter's `README.md` says for this harness, that the wiki pack's five
skills and each chosen pack's skills and roles are listed. A pack that is
installed and not listed is a pack that will silently not run.

A pack that ships roles carries its own README saying what each role does and
what it writes. Read it with the owner. A role kept without reading is a role
that will make decisions the owner did not agree to. Editing a role means
editing it in the pack's own repository, never in this tree, which holds no
copy.

Record, per pack: its name, its version, its marketplace, and the date the
listing was confirmed. That record goes into stage 5's decision entry.

---

## Stage 3: the sections a pack leaves empty

Some packs ship a section that cannot be written once for everybody: a buyer
segment, a jurisdiction's records of authority, a compliance calendar. The
pack's README names them. Work each one with the owner now, in the pack's own
repository, and never fill one from memory. Root rules 4 and 5 bind here as
hard as anywhere: a registry URL or a filing deadline from memory is exactly
the failure a research pack exists to prevent. Either research each row
against the authority's own page and cite it, or leave it reading "not
checked" and open an item saying so.

If no chosen pack ships such a section, say so and move on.

---

## Stage 4: the first source

The wiki is empty, and an empty wiki teaches nothing. Ingest one real source
before you finish, so the owner has seen the loop run once.

Ask for the best single document they already have about how they work: an
engineering standard, a process doc, a client onboarding note. Then run
`wiki-ingest` on it, exactly as the skill says. That means: copy it to
`central-context/raw/sources/YYYY-MM-DD-slug.ext`, read the whole thing, write
the source page, write the entity and concept pages it touches, update
`wiki/overview.md` and `index.md`, and append the log line.

Then run `wiki-lint` and show them the result.

If they have nothing to ingest, say so plainly and skip this stage. Do not
invent a source.

---

## Stage 4A: prove the harness

This stage proves the harness recorded in stage 0 and records the result in
the support matrix in `adapters/README.md`. It carries a letter so that the
numbers of the stages around it do not move. It has two halves, and only the
first can run today.

**First, the wiring.** Run `python3 scripts/check-harness.py` again, now that
stages 1 to 3 have edited the entrypoint and the wiki skills. Zero failures.
Then do the confirmation the adapter's `README.md` gives for this harness:
open a session at the root and see the wiki skills listed where that README
says they appear. Write the date into the `Wiring` column of that harness's row in the
support matrix, as `checked YYYY-MM-DD`, and into the "Wiring check" section
of the adapter's `README.md`. That column records a check of files and a
listing on screen, nothing more.

**Second, the behaviour. The test does not exist yet.**
`scripts/harness-acceptance.py` is named in `scripts/README.md` as not built,
and it is absent from the tree on 2026-09-12. So the four surface columns have
no command to run today. Do not improvise a substitute, and do not write a
result into a surface column from a reading of the files or from the listing
above. A cell that reads `not tested` is correct. A cell that reads `verified`
with no transcript behind it is a false claim.

What that half will be once the script lands: the test proves a harness by
checking four surfaces, which are the entrypoint loading without being asked,
one role dispatched, one skill loaded on demand, and one wiki operation
completed end to end. Each result goes into that harness's row in the support
matrix with the date of the run. A failing surface is a named finding in this
session's report and not a reason to stop the setup, because the workbench
still works on the surfaces that passed.

Write that half's commands from the script itself the first time you run it,
and add the script's row to the table in `scripts/README.md`.

---

## Stage 5: close out

**1. No markers left.**

```bash
grep -rn '^ *> FILL:' --include='*.md' .
```

Empty, or a named reason per remaining line.

**2. No half-replaced placeholders.**

```bash
grep -rn 'the owner\|the practice' --include='*.md' wiki/skills AGENTS.md | wc -l
```

The count is either zero, or it is every occurrence. Anything between means the
pass in stage 1 was partial. Finish it.

**3. The wiki skills are well formed, and every harness copy is current.**

```bash
python3 scripts/check-skills.py
python3 scripts/check-harness.py
python3 scripts/check-open-items.py
```

Zero failures from each.

**4. Close the open item.** `AGENTS.md` carries
`open_items: workbench-not-specialised`. It closes by work, and this was the
work. Follow `wiki-open-items`: remove the item from the frontmatter, append
the close line to `central-context/log.md`, and leave nothing struck through.

**5. Log the decisions.** Anything the owner settled in stages 0 to 3 that a
future session would otherwise re-litigate earns a `DECISIONS.md` entry. The
harness from stage 0 is one of them, and the set of packs and plugins, with
their versions and marketplaces, is another. Write each entry with the
question, the variants, and their answer.

**6. The neutral core stayed neutral.** This is the last check before the commit,
and it has two halves.

First, no file in the neutral core names a harness. The neutral core is
`AGENTS.md`, `central-context/`, `wiki/`, `scripts/`, `prompts/`,
`DECISIONS.md`, `README.md` and `.gitignore`. `SPEC.md` belongs to that list too,
and the template ships none, so nothing is missing while that file is absent.
`python3 scripts/check-harness.py`, which item 3 ran, scans those paths for
every pattern in `adapters/harness-names.txt` and reports each hit with its
file and line. One hit is a defect, whatever file it is in and whichever
harness it names. Fix it by moving the sentence into the adapter that owns it,
or by rewriting it to name no harness.

The `adapters/` path is not a harness name, and the scan strips it before it
matches. A neutral-core file may name that path, and any path below it, as
often as it needs to: telling a reader where the wiring lives is the opposite
of carrying the wiring. No count applies and no file is an exception.

Second, deleting the adapters directory leaves a workbench that still passes its
own checks. Run this against a copy. Never delete `adapters/` in the working
tree:

```bash
rm -rf /tmp/neutral-core-check
cp -R . /tmp/neutral-core-check
rm -rf /tmp/neutral-core-check/adapters
(cd /tmp/neutral-core-check && python3 scripts/check-skills.py && python3 scripts/check-harness.py)
rm -rf /tmp/neutral-core-check
```

Zero failures from both. The second, with no adapter left, has nothing to
declare and no pattern to scan for. Anything else means the neutral core
depends on something an adapter carries, and the fix belongs in the neutral
core: move the dependency into the adapter, or drop it.

**7. Commit.** Branch, commit, open a draft pull request. Never commit directly
to `main`. Root `AGENTS.md` carries the attribution lines.

---

## What you never do in this setup

- Fill a `> FILL:` marker with a plausible answer instead of asking.
- Write a filing deadline, a tax rate, a registry URL, or a rate benchmark from
  memory. Root rules 4 and 5 bind: retrieve it or record the gap.
- Write a result into the support matrix that no run produced.
- Pick one of two named variants on the owner's behalf. Root rule 8.
- Install a pack the owner did not choose, or skip one they did.
- Edit an installed pack's files in this tree. They are not here; edit the
  pack's own repository.
- Leave the placeholder pass half done.
