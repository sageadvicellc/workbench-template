---
name: wiki-verify
description: "Re-tests written claims against the disk, git, the sources, and the calendar, and moves the dates that prove it. Use on a cadence, before a research run or a plan embeds a fact from a context file, and whenever a page or an open item is old but nothing is broken. Covers old checked dates in open_items, disk facts that prose gets wrong, sources no page cites, closed questions still standing, draft pages that never moved, and the reading pass that re-tests a claim. Route a broken link or missing frontmatter to wiki-lint, and closing or opening an item to wiki-open-items."
---

# Wiki Verify

Lint tests the wiki against itself. Verify tests the wiki against the world.
To verify a claim means to test it against the disk, git, a source, or the
calendar, today. A page can be well formed, linked, and cited, and still wrong,
because the world moved after it was written. Nothing else catches that.

The case that produced this skill: an entrypoint stated the root repo had no
remote. The next day the repo had one, the wiki said so, and the entrypoint
still said it had none. Lint passed, because nothing about the file was
malformed. Nobody read the sentence again.

Verify moves dates and statuses. It does not decide. When a claim fails and the
fix is a decision, it stops and names the variants.

## Read this first

`central-context/AGENTS.md` is the page schema and names the log format. Its
`Open items schema` section names the fields this skill reads: `id`, `opened`,
`checked`, `triggers`, `asks`, `item`. Its rule 3 is the one this skill
enforces: `checked` moves when the item is verified, not when the file is
edited.

A context file is any `AGENTS.md`, any `SKILL.md`, any `SPEC.md`, and any page
under `central-context/wiki/`. Verify reads all of them.

The main session runs this skill. A role that finds a claim the disk
contradicts reports it in one `Context:` line, as the root `AGENTS.md` says
under "Keep the context true", and changes nothing.

## When to run

- On a cadence. The default is every 14 days. See the cadence note below.
- Before a research run, a quarterly plan, or a dossier embeds a fact that came
  from a context file. Container rule 4 binds there.
- When a page or an item is old and nothing is broken. That is the case lint
  cannot see.

## The mechanical checks

Run from the container root. Checks 2 to 5 print findings and nothing else, and
an empty result there is a pass. Check 1 is a script, and an empty result from
it is not a pass: it prints how many files it read, how many declare
`open_items:`, and how many items it parsed, and a file that declares a block
and yields no item is a failure.

**1. Old `checked` dates.**

An item whose `checked` date is older than the cutoff is a claim nobody has
tested. `scripts/check-open-items.py` computes the cutoff from the run date
inside the script, in Python, so it runs the same on macOS and on Linux. A
shell version that computes the cutoff with `date -v-14d`, the BSD form, fails
silently on a GNU system: the cutoff becomes an empty string, every comparison
against it is false, and the check reports a clean tree on every run.

```bash
python3 scripts/check-open-items.py --findings-only
```

`--stale-days` sets the window and defaults to 14. Every line under `Due.` is
an item to re-test in the reading pass below. A failure or a question above it
means the script did not read every file, so the due list is short: fix that
first, then run the check again. The script reads the context files listed in
`scripts/open-items-files.txt`, and an item in a file that list does not name
is never tested.

**2. Disk facts that prose gets wrong.**

The disk is the record of authority for what is on the disk. Gather the facts,
then read every sentence that states one.

```bash
r=$(git remote get-url origin 2>/dev/null || echo none); echo "remote: $r"
grep -rnoE 'github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+' --include='*.md' AGENTS.md central-context wiki/skills DECISIONS.md | grep -vF "${r#https://}"
grep -rniE 'no remote|has a remote|remote yet' --include='*.md' AGENTS.md central-context/AGENTS.md central-context/wiki wiki/skills
```

The first `grep` prints every repo URL in prose that is not the one on disk. The
second prints every sentence that makes a claim about the remote. Read each
one.

```bash
dirs='scripts|wiki/skills|prompts|central-context'   # add each project directory you nest here
grep -rhoE "\`($dirs)/[A-Za-z0-9_./-]*\`" --include='*.md' AGENTS.md central-context/AGENTS.md central-context/wiki | tr -d '`' | sort -u | while read -r p; do d="${p%%/*}"; [ -d "$d" ] || continue; [ -e "$p" ] || echo "missing: $p"; done
grep -rhoE '`(feat|fix|chore|test)/[A-Za-z0-9_.-]+`' --include='*.md' AGENTS.md central-context/wiki | tr -d '`' | sort -u | while read -r b; do git show-ref --quiet "refs/heads/$b" || echo "no local branch: $b"; done
```

The `dirs` list is the one line in this skill you maintain. Add a directory
the first time a context file names a path inside it, or the check silently
skips every claim about that project.

The path check skips a path whose top-level directory is absent from disk
altogether, which is what the `[ -d "$d" ] || continue` guard does. A project
tree that is ignored here and not checked out in this working copy would
otherwise report every one of its paths as missing. A branch a page cites with
no local ref has no such guard, so read that finding by hand: no local ref can
mean merged, deleted, or simply not fetched here.

A missing path is a finding only when the sentence says the path exists. A
sentence that says a path is gone, and it is gone, passes. A branch named on a
page that no longer exists locally was merged or deleted, and the page must
say which.

**3. A raw source that no page cites.**

A file in `raw/sources/` that no `sources` list names was filed and never
ingested, or was ingested and the page lost the citation. Either way the wiki
does not carry it.

```bash
cd central-context && find raw/sources -type f -name '*.md' | while read -r f; do grep -rqF -- "$f" wiki/ || echo "uncited: $f"; done; cd ..
```

**4. A closed question still standing.**

The `open_items` schema, rule 1: closing an item removes it. A question marked
resolved under `## Open questions` is a closed item that was left in place.

```bash
for f in $(find central-context/wiki -name '*.md'); do awk '/^## Open questions/{s=1;next} /^## /{s=0} s && /[Rr]esolved/{print FILENAME": "$0}' "$f"; done
```

Remove the entry. The dated correction on the page, and the log line, are the
record.

**5. A draft that never moved.**

A page at `status: draft` older than the cutoff either earned `current` and
nobody said so, or is waiting on a source that never came.

```bash
cutoff=$(date -v-14d +%F)
grep -rl '^status: draft' central-context/wiki --include='*.md' | while read -r f; do c=$(grep -m1 '^created:' "$f" | cut -d' ' -f2); [[ "$c" < "$cutoff" ]] && echo "draft since $c: $f"; done; true
```

## The reading pass

These need reading, not grep. Bound the pass to what the mechanical checks
flagged, plus every `open_items` item, plus every `draft` page. Do not re-read
the whole wiki on every run.

**6. Re-test every flagged item.**

For each item, read the `item` paragraph and test the claim it makes against the
disk, git, or a source, today. Three outcomes:

- The claim holds. Move `checked` to today. Change nothing else.
- The claim no longer holds because work was done or the world moved. Do not
  edit the item here. Hand it to `wiki-open-items` in the same session, which
  closes it and writes the record.
- You cannot tell. Leave `checked` where it is and say so in the report. A
  date that moved on a guess is worse than an old one.

**7. Re-test the flagged pages.**

For each page check 2 or check 5 named, read `## Key points` and test each
claim about the disk, a repo, a date, or a status. When a claim fails:

- The fix is a fact the disk settles: write a dated correction on the page, in
  the form `wiki-ingest` uses. Cite the disk as what you tested.
- The fix needs a source the wiki does not hold: set `status: stale`, add the
  gap under `## Open questions`, and name the source an ingest needs.
- The fix is a decision: stop. See below.

**8. Sources moved on.**

A `source` page lists the pages its ingest changed. Open each one and make sure
that its `sources` list names the raw file. A page that dropped the citation
was rewritten without the source in front of the writer. Set it `stale` and
say which claims lost their citation.

## What verify changes, and what it never touches

Changes: `checked` dates, `status` between `current` and `stale`, a dated
correction on a page, an open question added, a resolved entry removed.

Never: a file in `raw/`, the body of an `open_items` item, an item's `id`, a
file another agent holds in the same session, or any decision that is the owner's.

## Stop and ask

Stop when a claim fails and the fix is a decision. State the claim, what the
disk says instead, and named variants. Do not pick one.

- Two context files state the same fact differently and neither is the
  authority. Variants: name one file the authority and correct the other, or
  move the fact into the wiki and have both point at it.
- A page's claim failed and the source it cites is what is wrong. Variants:
  file a new source that corrects it, or leave the page `stale` with the gap
  stated.
- The cadence. Nothing published settles it. Variants: 14 days as this skill
  defaults, 7 days as the one first-hand account of a weekly lint ran, or run
  only before a deliverable embeds a context-file fact.

## Report and log

Say what was tested, what moved, what went `stale`, what was handed to
`wiki-open-items`, and what you could not tell. Append one line to
`central-context/log.md`:

```
YYYY-MM-DD · verify · <N items, N pages tested> · <N checked moved, N stale, N handed to open-items, N stopped for the owner>
```

A clean run still gets a line. It is the only evidence the pass ran.

## Provenance

First-party to the practice this template came from, written 2026-09-11. The
published record on keeping an LLM wiki
from rotting is thin. Karpathy's gist (2026-04-04) names one periodic health
check for contradictions, stale claims, and orphans, with no cadence and no
method. One first-hand account states a cadence. Jim Liu ran the pattern for six
months over 35 pages, with a weekly lint and a fortnightly contradiction pass.
He added a `last_verified` field per page after stale and fresh figures sat
side by side. The `checked` field here does the same work at the item level. The
disk-fact checks are this practice's own, from the remote claim that went
stale in one day.

## Not this skill

- A broken wikilink, missing frontmatter, a duplicate subject, or two pages
  that contradict each other. Use `wiki-lint`.
- Opening an item, matching items to the work in hand, putting the `asks`
  question to the owner, or closing an item. Use `wiki-open-items`.
- Filing a source that corrects a stale page. Use `wiki-ingest`.
- Answering a question from the wiki. Use `wiki-query`.
