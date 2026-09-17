---
open_items:
  - id: workbench-not-specialised
    opened: 2026-09-11
    checked: 2026-09-11
    triggers: [first real task in this workbench, dispatching any agent role, writing a client-facing artifact, any FILL marker]
    asks: ""
    item: >
      This workbench is a fresh clone of the template and nothing in it has
      been specialised yet. Ten `> FILL:` markers are still standing, all in
      this file, which means the always-on rules name no writing standard, no
      confidential names, and no identity, and no pack or plugin has been
      chosen for code, design, or research. Closing this takes one pass of
      `prompts/setup.md`, after which every line is gone. Check with
      `grep -rn '^ *> FILL:' --include='*.md' .`
---

# AGENTS.md: the workbench

Entrypoint. Read at the start of every session. A session runs from this
directory and from nowhere else, so this file loads every time and nothing
below it does until the routing table sends you there.

A harness is the program that runs the agent loop and reads these files. Five
harnesses document reading a file of this name at session start, each checked
at its own documentation on 2026-09-11. A harness that needs a different
filename, or its own discovery path, gets both from its adapter. The routing
table carries the row that leads there.

This file is short on purpose. When it starts growing, that is the signal to
move something into the wiki, not to add a section here.

> FILL: replace this paragraph with one that says what this workbench is for
> and when it was set up. `prompts/setup.md` covers it.

---

## Identity

> FILL: who the agent is acting as, and who owns the decisions. One paragraph.
> The example this template came from read:
>
> Senior TypeScript and React engineer acting on behalf of <name>, owner of
> <business>. Principal-engineer judgment. Prefer reversible actions. Stop
> before irreversible ones. You are the IC. <name> is the tech lead.
>
> Every skill in `wiki/skills/` says "the owner" where that name goes. Leave
> the phrase alone or replace it everywhere; do not do half.

---

## Always on

These bind every response and every artifact, on every surface. They outrank
any skill, including the ones installed here.

The numbering is load-bearing. Skills and roles, installed or your own, cite
rules 4, 8, 9 and 10 by number. Change what a rule says; do not renumber it.

1. **Reserved.** Your workbench's own rule, or left empty.
2. **Plain language governs output written here.** Short sentences, active
   voice, simple tenses, one word one meaning, condition before command, every
   technical term defined at first use. A chat reply is three sentences at
   most.
   > FILL: name the writing-standard skill that carries this, and where it is
   > installed from, or delete this marker and let the rule stand on its own.
3. **The interface and copy standards bind anything a person looks at.**
   > FILL: name those skills and the packs or plugins they arrive in, and say
   > which binds interface work and which binds client-facing copy. Neither
   > binds ordinary chat, where rule 2 governs.
4. **Verify before embedding.** Any date, figure, name, appointment, price, or
   record bound for an artifact gets checked first. Never carry a fact from
   training memory into a deliverable, and never carry one from an archived
   note either.
5. **Missing data is a finding.** Say a figure does not exist. Never
   interpolate, estimate into a gap, or reconstruct a URL from memory.
6. **Honest over optimistic.** Name hard constraints plainly. Report what was
   verified and what could not be.
7. **Artifacts stay pure content.** Rationale, process notes, and caveats live
   in chat, never in the deliverable.
8. **Surface decisions that belong to the owner or their client** rather than
   deciding them silently. Offer named variants, not one option presented as
   settled.
9. **Names that never appear in client-facing material.**
   > FILL: list the employers, clients, or partners that must not be named,
   > or write "None" and leave the rule standing. Several skills cite rule 9
   > by number.
10. **Terse by default.** No filler, hedging, pleasantries, preamble,
    tool-call narration, or a closing summary that repeats what is above it.
    Keep articles and full sentences. Every technical fact survives; only
    padding dies. This binds agent reports hardest, because nobody reads those
    twice.

---

## Irreversible, stop and confirm

- Dropping database tables or columns
- Deleting untracked files
- Pushing to `main` or merging pull requests
- Calling billing or payment APIs
- Modifying production row-level security policies
- `git reset --hard` or `git push --force`

Commit a checkpoint before any schema operation, file deletion, external API
call, or anything with no obvious undo.

---

## How work runs

Nothing that does work ships in this tree. The template is the structure: an
entrypoint, a knowledge base, and the checks that keep both true. The skills,
roles, and pipelines that do the work arrive as packs and plugins, chosen at
setup and installed per machine on each harness. `prompts/setup.md` asks which
ones, and `README.md` lists one practice's working set as an example, not as a
default.

**The knowledge base.** The five wiki operations are the one pack this
template ships, `wiki/`, because the schema in `central-context/AGENTS.md`
depends on them. Install it from this repo, or bring a pack of your own that
runs the same five operations.

**Code, and anything built.**
> FILL: name the plugin or pack that carries an idea to a draft pull request,
> and its install command. Describe the work and let it route. Do not write a
> specification or a plan by hand first. If nobody builds software here, say
> so instead of leaving a pipeline nobody runs.

**Research.**
> FILL: name the pack that carries the research roles and their operating
> procedure, or write "None" and delete the research row from the routing
> table.

Work that fits no pack is done in the main session, under the always-on rules.

---

## Routing

Read this file, then read only what the table sends you to.

| Task | Use |
|---|---|
| Setting this workbench up for the first time | `prompts/setup.md` |
| Which harnesses this workbench runs on, and how to wire one up | `adapters/README.md` |
| Code: a feature, a fix, a script, a repo | the plugin named under "How work runs" |
| Reviewing a diff before a pull request | that plugin's review skill or role |
| What the workbench knows about a person, company, project, decision, or figure | the `wiki-query` skill, `wiki/skills/wiki-query/SKILL.md` |
| A new source that needs to enter the knowledge base | the `wiki-ingest` skill, `wiki/skills/wiki-ingest/SKILL.md` |
| Health check the knowledge base | the `wiki-lint` skill, `wiki/skills/wiki-lint/SKILL.md` |
| A context claim that may have gone stale, before a fact is embedded | the `wiki-verify` skill, `wiki/skills/wiki-verify/SKILL.md` |
| An open item: matching it, asking it, opening it, or closing it | the `wiki-open-items` skill, `wiki/skills/wiki-open-items/SKILL.md` |
| The wiki's layout, page types, frontmatter, or the open items schema | `central-context/AGENTS.md` |
| Research on a market, a competitor set, a purchase, a prospect, or a quarterly plan | the research pack named under "How work runs", and its operating-procedure skill |
| A decision that was settled, and why | `DECISIONS.md` |
| Writing code in a repo here | that repo's `AGENTS.md`, then its `SPEC.md` |

> FILL: replace the three rows above that point at "How work runs" with the
> plugin, pack, and skill names chosen there, then add a row per skill your
> packs install that a session should route to by name: the writing standard,
> the brand or visual identity skill, the engineering standard. Name the pack
> beside the skill, as the wiki rows do.

A wiki row names a skill and its path because no harness is guaranteed to
find the skill on its own. If nothing loads it for you, read the path. A skill
from an installed pack has no path in this tree; name the pack, and a harness
that cannot load it reads the pack's own README.

A question the wiki cannot answer is a reason to ingest the source that answers
it, so the next session does not repeat the read.

Two conventions bind every wiki page, and neither is guessable from the content.
A page links with wikilinks, page names inside double square brackets, in its
`## Links` section. A page carries YAML frontmatter. Both are mandatory. The
page schema in `central-context/AGENTS.md` is the authority, and a session
started here does not load that file by itself, so read it before you write a
page.

---

## What is on disk

The workbench root is one git repo. It tracks everything below except the
project repos you nest here, which have their own remotes and are ignored.

| Path | Holds | Git |
|---|---|---|
| `central-context/` | The knowledge base. An LLM wiki. Sources in `raw/`, compiled pages in `wiki/`, research deliverables in `docs/`. No code, ever | Root repo |
| `wiki/` | The one pack this template ships: the five wiki skills under `wiki/skills/`, with the manifests a harness installs it from | Root repo |
| `scripts/` | Everything executable that is not a skill's and not a project's | Root repo |
| `prompts/` | Prompts a person pastes in on purpose. Not loaded by anything | Root repo |
| `DECISIONS.md` | The append-only decision log. The main session writes it | Root repo |

> FILL: add one row per project repo you nest here, and add its directory name
> to `.gitignore` and to the `dirs` list in the `wiki-verify` skill.

No other skill and no role lives in this tree. They arrive in packs, installed
per machine on each harness, and a pack's own README says where its files land.
A skill in `wiki/skills/` is discovered only when its directory sits directly
under that path with a `SKILL.md` inside it; nesting one a level deeper
disables it silently. A harness that needs a symlink or a generated file to
find this tree gets it from its adapter, declared there and checked by
`python3 scripts/check-harness.py`. Edit `.mcp.json`, run
`python3 scripts/sync-harness.py`, and never edit the copy.

In `.gitignore`, a path with square brackets in it needs them escaped, because
git reads `[...]` as a glob character class.

---

## Version control

Never commit directly to `main` in any repo here. Branch, commit, open a draft
pull request. The owner approves and squash-merges.

Run the repo's gates before every commit. In a Node repo that is `typecheck`,
`lint`, `test`, and `build`, all four reporting zero errors. New code with no
tests is a blocked commit.

Run `python3 scripts/check-skills.py` before any commit that touches
`wiki/skills/`. A harness skips a malformed skill file in silence and nothing
else catches it. Run `python3 scripts/check-open-items.py` before any commit
that touches an `open_items` block. An item the script cannot read blocks
nothing. Run `python3 scripts/check-harness.py` before any commit that touches
`.mcp.json` or anything under `adapters/`. A generated file that drifts from
its source is a server that works on one harness and silently not another.

> FILL: once the engineering standard is ingested, this section becomes a
> summary and the wiki page becomes the authority. Name the page here.

End a commit message with the attribution lines the session gives you.

---

## Keep the context true

Nothing checks the wiki or an `open_items` block. A session does, or nobody
does.

Four things fire, each on its own trigger, never because work happened:

1. **Work proved a context claim wrong.** Fix the file in the same session and
   log the correction. `wiki-verify` says how.
2. **The task matched an open item's `triggers`.** Put that item's `asks`
   question to the owner with named variants, then stop that thread until they
   answer. `wiki-open-items` says how.
3. **A role returned a line starting `Context:`.** It reported a fact, a
   gap, or a contradiction and wrote nothing itself. Filing it is yours.
4. **The owner gave the same correction twice.** It becomes a skill line or a
   hook line, written by the session that notices, with one `log.md` line.

A role never writes a context file. The main session does, because a role sees
one task and cannot judge what the workbench as a whole now knows.

---

## Open items

Unresolved questions live in the frontmatter at the top of this file, under
`open_items`. No prose section holds them.

The schema is in `central-context/AGENTS.md`, under "Open items schema". The
`wiki-open-items` skill matches, asks, opens and closes. The `wiki-verify`
skill re-tests an item whose `checked` date has gone old.
