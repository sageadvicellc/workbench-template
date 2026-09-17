---
name: wiki-ingest
description: "Files a source into the central-context wiki and compiles it into pages. Use when a document, transcript, note, export, or archived vault file needs to enter the knowledge base. Covers filing to raw/, choosing a domain, writing the source page, updating entity and concept pages, recording a contradiction, and appending to the log. Route a question answered from pages that already exist to wiki-query, and a health check to wiki-lint."
---

# Wiki Ingest

Ingest is how a claim earns a place in the wiki. Nothing reaches `wiki/` any
other way. A file copied into `wiki/` without an ingest is a bug, and the fix
is to delete it and ingest the source properly.

## Read this first

`central-context/AGENTS.md` is the schema. It states the layout, the page
types, the frontmatter fields, and the section order. Read it before writing a
page. When this skill and that file disagree, that file wins and this skill
gets corrected.

## What a source is

A source is a record of something someone said, wrote, measured, or shipped.
An email, a transcript, an invoice, a contract, a screenshot, a vault note, a
web page saved to disk.

A source is not a conclusion. If the thing in front of you is already a
synthesis, it is still a source, and the claims inside it are still claims that
need attribution to whoever wrote it.

## Procedure

**1. File the source.**

Copy it to `central-context/raw/sources/`. Name it `YYYY-MM-DD-slug.ext`, where
the date is when the source was created, not when you filed it. If the creation
date is unknown, use the filing date and say so on the source page.

Attachments go to `raw/assets/` with the same name and a suffix.

Never edit a file in `raw/`. Not a typo, not a broken link, not the formatting.

**2. Read the whole thing.**

Do not summarise from the first screen. A source that is too long to read in
one pass gets an ingest per section, and each one gets a log line.

**3. Classify it.**

Say what kind of source it is and which domain it belongs to.

If no domain fits, stop and ask. Do not invent a domain to hold one source. A
domain is created when a third source lands on the same subject, and until then
the source page sits in the closest existing domain with an open question
saying it may not belong there.

**4. Write the source page.**

`wiki/domains/<domain>/sources/<slug>.md`, type `source`. One page per source.
Follow the schema. Every key point cites the raw path.

Separate what the source says from what you conclude. A conclusion is labelled
as one, or it goes under `## Open questions`.

**5. Update what the source touches.**

Every person, company, product, and place gets an entity page. Every topic,
method, and thesis gets a concept page. Create the ones that do not exist,
update the ones that do, and add the new source to their `sources` list and
their `updated` date.

Cross link both ways. A new page that nothing links to is a page nobody finds.

**6. Update the maps.**

Update the domain `overview.md`. Update `wiki/overview.md` only if the domain
map itself changed.

**7. Record it.**

Add a line to `index.md` for every page created. Append one line to `log.md`:

```
YYYY-MM-DD · ingest · raw/sources/<file> · created N, updated N
```

## When a source contradicts a page

Do not overwrite the page. Write a dated correction on it saying what the page
used to claim, what replaced it, and which source did it. The audit trail is
the point. A knowledge base that revises claims in place has no way to show
what it used to believe, which is how one stops being trustworthy.

When the two sources are both credible and disagree, the page states the
disagreement. It does not pick a winner silently.

When the source answers a question under `## Open questions`, or closes an
`open_items` entry in any context file, remove the question in the same
ingest. Do not leave it marked resolved. The dated correction and the log line
are the record. The close itself follows `wiki-open-items`.

## Ingesting an old note

Most workbenches start by migrating something: an old notes vault, a wiki, a
folder of docs. These rules govern that.

- A note is a claim by whoever wrote it, on the date in its frontmatter. It is
  not a verified fact. Treat a `consolidated` or `reviewed` date as the last
  time someone looked, not as proof the claim still holds.
- Anything that does not survive the read is dropped on purpose. Say what you
  dropped in the log line. Do not carry a claim forward because deleting it
  feels wasteful.
- Skills, agents, scripts and plugins are code. They do not get ingested. They
  move by copy, to `scripts/` at the container root or to their own repo.
- Migrate one source at a time. Batching is what makes a migrated knowledge
  base unauditable, because nobody can say afterwards which claims were read.

## Stop and ask

- No domain fits and it is not the third source on the subject.
- The source contains a figure, price, date, or name bound for a client
  artifact that you cannot verify.
- The source contradicts a page and you cannot tell which is right.
- The source is a file you were asked to ingest that lives outside `raw/` and
  filing it would mean copying something large or private.

## Not this skill

- Answering a question from pages that already exist. Use `wiki-query`.
- Checking the wiki for broken links, duplicates, or contradictions. Use
  `wiki-lint`.
- Re-testing an old page or item against the disk, git, or a source. Use
  `wiki-verify`.
- Closing the item a source answers, or putting its question to the owner. Use
  `wiki-open-items`.
