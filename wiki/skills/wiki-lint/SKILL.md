---
name: wiki-lint
description: "Health checks the central-context wiki against itself and fixes only what the check flags. Use before a commit to the knowledge base, after a batch of ingests, and whenever pages feel duplicated or contradictory. Covers broken wikilinks, missing frontmatter, source paths that do not resolve, duplicate subjects, contradictions between pages, and index parity. Route a page or item that is old but not broken to wiki-verify, filing a new source to wiki-ingest, and answering a question to wiki-query."
---

# Wiki Lint

Lint is the gate. There is no build here and no test suite, so this is the only
thing standing between a wiki that compounds and a wiki that rots into a pile
of half-true pages nobody trusts.

Fix only what the check flags. Lint is not a rewrite pass.

## Read this first

`central-context/AGENTS.md` names the checks. That file is the authority. When
it lists a check this skill does not, run it anyway and correct this skill.

## The six checks

Run from `central-context/`.

**1. Every wikilink resolves to exactly one page.**

```bash
grep -rho '\[\[[^]]*\]\]' wiki/ index.md | sort -u | tr -d '[]' | while read -r n; do
  c=$(find . -name "$n.md" -not -path "./raw/*" | wc -l | tr -d ' ')
  [ "$c" = "1" ] || echo "$n resolves to $c pages"
done
```

Zero means a broken link. Two or more means a duplicate subject, which is check
five wearing a different mask.

**2. Every page carries the frontmatter its type requires.**

Every page in `wiki/` states `type`, `status`, `created`, `updated`, and
`sources`. Every type except `overview` names at least one source.

```bash
for f in $(find wiki -name '*.md'); do
  for k in type status created updated sources; do
    grep -q "^$k:" "$f" || echo "$f missing $k"
  done
done
```

**3. Every sources entry names a file that exists.**

A `sources` list pointing at a file that is not in `raw/` means the page was
written from something other than a filed source. That is the failure the whole
pattern exists to prevent, so treat it as the most serious finding on this
list.

**4. No two pages cover the same subject.**

This one needs reading, not grep. Two entity pages for the same company under
different spellings, a concept page and a query page saying the same thing, a
source page that grew into a concept page.

Merge into the older page, keep every citation from both, move the loser to
`wiki/archive/`, and leave the archived page in place with a line saying what
absorbed it. Never delete.

**5. No page contradicts another page.**

Also reading, not grep. Look for the same figure, date, status, or name stated
differently on two pages.

Do not resolve a contradiction by picking the page you read first, and do not
fix it by editing both. Go back to the sources each page cites. If the sources
disagree, the pages state the disagreement and stop. If one page is simply
older, correct it with a dated correction and say what replaced what.

**6. Index parity.**

Every page in `index.md` exists, and every page exists in `index.md`. A page
missing from the index is invisible, because `wiki-query` starts there.

## Also worth a look

Not a gate, but read for these while you are in there:

- **Orphans.** A page nothing links to.
- **A thin active wiki with a thin archive.** The archive must be the larger
  of the two. If it is not, pages are being kept that must have been merged.

A page that is old but not broken is not a lint finding. Lint tests the wiki
against itself. `wiki-verify` tests it against the disk, git, the sources, and
the calendar, and that is where an `updated` date far behind its sources goes.

## Report

Say what failed, what you fixed, and what you left. Append one line:

```
YYYY-MM-DD · lint · <what failed> · <what was fixed>
```

A clean run still gets a line. It is evidence the check ran.

## Stop and ask

- A contradiction whose sources genuinely disagree.
- A merge that would drop a citation.
- More than a handful of findings at once. That is a schema problem, not a page
  problem, and the fix belongs in `AGENTS.md`.

## Not this skill

- Filing a new source and compiling it. Use `wiki-ingest`.
- Answering a question. Use `wiki-query`.
- A claim that is old but not broken: an item whose `checked` date is old, a
  page the disk contradicts, a draft that never moved. Use `wiki-verify`.
- Opening, matching, asking, or closing an `open_items` entry. Use
  `wiki-open-items`.
