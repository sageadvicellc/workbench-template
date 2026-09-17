---
name: wiki-query
description: "Answers a question from the central-context wiki and cites the pages it came from. Use when someone asks what is known about a person, company, product, project, decision, or figure, and the answer should come from the knowledge base rather than from memory or a fresh search. Covers reading the index, synthesising across pages, citing by path, reporting a gap instead of filling it, and saving an answer worth keeping. Route filing a new source to wiki-ingest, and health checks to wiki-lint."
---

# Wiki Query

The wiki exists so a question is answered once and stays answered. A query
reads compiled pages. It does not re-read the sources, and it does not answer
from memory.

## Read this first

`central-context/AGENTS.md` states the layout and the page schema. Read it if
you are about to write a page.

## Procedure

**1. Start at the index.**

Read `central-context/index.md`. It is one line per page, grouped by domain.
Open the pages it points to. Do not glob the wiki or read the whole tree.

**2. Read out from there.**

Follow `[[wikilinks]]` from the pages you opened. A page names its neighbours,
so two hops usually cover a question. Stop when new pages stop adding claims.

**3. Answer from the pages.**

Cite each claim by page path. The reader needs to be able to open the page and
see the same sentence.

State the shape of the answer before the detail. Short sentences.

**4. Say what is missing.**

Missing data is a finding. Three outcomes, and none of them substitute for
another:

- **The wiki answers it.** Cite the pages.
- **The wiki holds nothing on it.** Say so, and name what would have to be
  ingested to answer it.
- **The wiki holds something stale or contradictory.** Say which pages
  disagree, and give both readings. Do not average them. A page at
  `status: stale` is cited as stale, with the gap the page states.

If the answer is a claim about the disk, a repo, a branch, or a date, and the
page is old, do not pass it on untested. Say it is untested, or run
`wiki-verify` on that page first.

Never estimate into a gap. Never reconstruct a figure, a date, or a URL from
memory and present it as a wiki answer.

**5. Do not read the raw sources by default.**

If the compiled pages do not answer it, the answer is that the wiki does not
answer it. Reading `raw/` is allowed when the user asks, and then the reply
says plainly that it came from a source and not from a page.

That is a signal, not a workaround. A question that keeps sending you to `raw/`
is a question the wiki should have compiled, so propose an ingest.

**6. Keep the answer if it will be asked again.**

Save it to `wiki/domains/<domain>/queries/<slug>.md`, type `query`, when both
are true:

- Answering it took real reading across three or more pages.
- The question will come back, from the owner, a client, or a future session.

Do not save a lookup that one page already answers. That page is the answer,
and a query page beside it is a duplicate that lint will flag.

**7. Log it.**

```
YYYY-MM-DD · query · <the question, short> · answered from N pages
```

Log the query even when the answer was a gap. A run of logged gaps on one
subject is the strongest signal about what to ingest next.

**Unless you are a role, in which case do not.** `research-operations` states
that no role writes to `wiki/`, `raw/`, `index.md`, `log.md`, or
`DECISIONS.md`, and that rule wins: a role queries the wiki often and a log
line per role per query would bury the ingests. A role that queried the wiki
reports it in a `Context:` line instead, and the main session writes the log.
This step is the main session's.

## Not this skill

- Filing a new source and compiling it. Use `wiki-ingest`.
- Checking the wiki for broken links, duplicates, or contradictions. Use
  `wiki-lint`.
- Re-testing an old page or item against the disk, git, or a source. Use
  `wiki-verify`.
- Putting an open question to the owner, or closing one. Use `wiki-open-items`.
- Researching a prospect or a market for a client artifact. Use
  `prospect-research`, which sets the admission rules for a fact that will be
  cited outside the practice.
