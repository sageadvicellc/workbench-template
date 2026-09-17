# workbench-template

A starting structure for a workbench built around an LLM wiki: a knowledge base
an agent compiles from sources and keeps current, plus the checks that keep it
true. It ships the structure and one pack, the five operations that run the
wiki. Everything else that does work, the code pipeline, the design tools, the
research team, is a pack or plugin you choose at setup and install on your own
harness. Nothing is pre-installed and nothing is forced.

Clone it, run one setup pass, and you have a second brain your agents read
before every task and correct when the world moves.

## What is in here

```
workbench/
  AGENTS.md            the entrypoint. Read at the start of every session
  DECISIONS.md         append-only decision log
  .gitignore           project repos you nest here stay untracked
  .mcp.json            MCP servers, the one source every harness is wired from. Empty
  adapters/            one thin adapter per harness: a manifest, a README, and nothing else
  wiki/                the one pack this template ships: the five wiki skills and their manifests
  scripts/             the checks and the generator, with their tests
  prompts/             setup.md, and prompts you paste in on purpose
  central-context/     the knowledge base
    raw/               sources, immutable, written by a person
    wiki/              pages compiled from raw/, written by the agent
    docs/              research deliverables, outside the wiki pattern
    AGENTS.md          the schema: layout, page types, frontmatter, operations
    index.md           the catalog, one line per page
    log.md             append-only, one line per operation
```

The rule that makes it work: a source enters `raw/` once and is never edited.
An agent reads it and compiles what it says into `wiki/`. Questions are
answered from `wiki/`, with a citation, not from the sources and not from
memory. Knowledge is compiled once instead of re-derived on every question.

The pattern is Andrej Karpathy's LLM wiki, published April 2026. The five
operations, the open-items schema, and the verify pass are this template's own.

## The five wiki operations

| Skill | Runs when |
|---|---|
| `wiki-ingest` | A new file lands in `raw/` |
| `wiki-query` | Someone asks what is known |
| `wiki-lint` | Before a commit. Checks the wiki against itself |
| `wiki-verify` | On a cadence. Checks the wiki against the disk, git, and the calendar |
| `wiki-open-items` | At the start of a task. Surfaces questions nobody has settled |

Lint catches a wiki that is inconsistent. Verify catches a wiki that is merely
old, which is the failure that actually happens.

## Getting started

```bash
git clone https://github.com/sageadvicellc/workbench-template.git my-workbench
cd my-workbench
python3 scripts/check-harness.py
```

`0 failure(s)` means every supported harness is wired: the symlinks and
generated files each one discovers the tree through are tracked in git, so
there is nothing to install. On Windows, turn on Developer Mode or run as
Administrator, then clone with `git clone -c core.symlinks=true`. Never use a
zip download, which flattens a symlink into a text file. The check names the
fix if it finds one.

Open your harness at that directory. The install steps per harness, the wiki
pack first and then whatever packs you choose, and a confirmation that the
surfaces loaded, are in its adapter's `README.md` under `adapters/`. Then
paste `prompts/setup.md` into the session. It interviews you, fills in every
placeholder, asks which packs and plugins carry your code, design, and
research work, and ingests your first real source so you have seen the loop
run once.

Setup takes one sitting. Skipping it leaves a workbench that describes someone
else's business.

## More than one harness

A harness is the program that runs the agent loop and reads these files. This
workbench is built to run on more than one, and no harness has been verified on
it yet. The entrypoint, the knowledge base and the wiki skills name none of
them, and each harness gets a thin adapter that holds only its own wiring: how
it finds the entrypoint, how it installs a pack, how it spells an MCP server,
and what happened the last time somebody ran it. The directory listed above is the place
to look, and one routing row in `AGENTS.md` points there.

The wiring itself is tracked: a symlink where a harness looks for the
entrypoint, and, where a harness spells an MCP server its own way, a file
`scripts/sync-harness.py` generates from `.mcp.json`. Edit the source and run
the generator; never edit the copy. `scripts/check-harness.py`
proves every link and every generated file, and fails if a file in the neutral
core names a harness.

Two adapters ship today, and their wiring checks clean, read 2026-09-17. Every
surface cell in the support matrix there still reads `not tested`, so what is
built is the structure and not a proven run.

## The vault configuration is yours

Wikilinks and page frontmatter are deliberate conventions, not incidental ones.
The owner settled both on 2026-09-11 and accepted one outside dependency to carry
them, which is Obsidian. The decision records three reasons. Obsidian costs
nothing, it is in common use for reading markdown, and it resolves a wikilink and
reads page frontmatter with no setup. Its pricing page states the free tier as
"Free without limits. No sign-up required. No strings attached." and says a
commercial license is encouraged and not required
(`https://obsidian.md/pricing`, retrieved 2026-09-12).

The template therefore ships no `.obsidian/` directory and needs none to read.
Obsidian generates links in wikilink form by default: "By default, due to its
more compact format, Obsidian generates links using the Wikilink format"
(`https://obsidian.md/help/links`, retrieved 2026-09-12).

Almost nothing that ships carries a wikilink, because nothing is ingested yet.
Three files under `central-context/` hold a pair of double square brackets, on
seven lines in total, read 2026-09-12. Two of those seven lines are live links,
and they point at each other: the wiki map `central-context/wiki/overview.md`
links `[[index]]`, and the catalog `central-context/index.md` links
`[[overview]]`. The other five lines sit inside code spans in
`central-context/AGENTS.md`, which quotes the convention while stating it, so they
are examples and not links. That is the whole of it until your first ingest. The
convention binds every page you write, per the page schema, and Obsidian's default
is what makes it work with no configuration.

One manual check proves that, and **nobody has run it.** Open a fresh clone as a
vault. Add no configuration, keep the default theme, enable no community plugin.
Write two pages under `central-context/wiki/`, link one to the other with a
wikilink, and click it. It resolves to its target. The check is manual because
nothing here drives Obsidian, and it stays unrun until somebody writes down the
date they ran it.

Two settings are worth your own minute. Leave `Use [[Wikilinks]]` on, under
**Settings > Files and links**, so a page you write later still matches the page
schema instead of landing as a CommonMark link (`https://obsidian.md/help/links`,
retrieved 2026-09-12). Point `Default location for new notes` at a folder so a
new note does not land in the vault root (same page and date). Attachments have
their own setting, `Default location for new attachments`, documented on its own
page as **Settings → Files & Links → Default location for new attachments**
(`https://obsidian.md/help/attachments`, retrieved 2026-09-12).

Pane layout, theme and plugins stay personal, and no plugin code is vendored
here. `.gitignore` already names the per-person state, so a vault you do
configure keeps its view state out of a commit.

## Two conventions the knowledge base depends on

Both are mandated by the page schema in `central-context/AGENTS.md`, and that
file states them in full beside the reason.

- **Wikilinks**, a page name inside double square brackets, as in
  `[[branch-discipline]]`. `wiki-lint` resolves every one of them to exactly one
  file, and `wiki-query` follows them from a page to its neighbours, so they
  carry navigation and not decoration.
- **YAML page frontmatter** on every page, which is also where an open item
  lives, so the convention carries the unresolved questions too.

## Packs and plugins

The template ships one pack, `wiki/`, declared by the marketplace manifest at
the root. It holds the five skills above and nothing else, because the page
schema in `central-context/AGENTS.md` depends on them. Install it from this
repo, or bring a pack of your own that runs the same five operations.

Everything else is yours to choose. `prompts/setup.md` asks, in stage 0, which
plugin carries code to a draft pull request, which skills bind anything a
person looks at, which writing standard governs output, and which pack carries
a research team, if any. The answers go into `AGENTS.md` under "How work runs"
and into the routing table, and the install commands go into your harness, not
into this tree. A workbench that names no pipeline is a legitimate outcome; a
workbench that ships one nobody chose is not.

One working set, as an example and not a default. The practice this template
came from runs, as of 2026-09-17:

| Need | What it uses | Where from |
|---|---|---|
| Code to a draft pull request | ECC, `ecc@ecc` | `claude plugin marketplace add affaan-m/ECC` |
| Writing standard | `simple-english` 2.1.x | `claude plugin marketplace add AminBlg/SimpleEnglish` |
| Anything a person looks at | `impeccable`, `ui-ux-pro-max`, `taste-skill` | `pbakaus/impeccable`, `nextlevelbuilder/ui-ux-pro-max-skill`, `Leonxlnx/taste-skill` |
| The wiki | this repo's `wiki` pack | `claude plugin marketplace add sageadvicellc/workbench-template` |
| Research team, brand, asset prompts | its own private packs | a private marketplace, per practice |

That practice enables ECC per repository rather than per machine, because a
plugin that loads hooks and skills into every session costs tokens in every
session. Whatever you choose, measure the always-on cost of a plugin before you
enable it everywhere; `claude plugin details <name>` reports it on one harness,
and the other harnesses' adapters say what to run there.

## Requirements

- Python 3 for the scripts under `scripts/`
- Git, with symlinks enabled, which is the default everywhere but Windows
- An agent harness that one of the adapters covers, or a few hours to add one

No build step, no dependencies, no install.

## Conventions worth knowing before you edit

- `central-context/` holds no code, ever. Executables go in `scripts/`.
- A skill is one directory directly under `wiki/skills/` with a `SKILL.md`
  inside it. Run `python3 scripts/check-skills.py` before any commit touching
  it. A malformed skill file is skipped in silence, so the script is the only
  thing that will tell you.
- After any edit to `.mcp.json`, run `python3 scripts/sync-harness.py` and
  commit what it wrote. `python3 scripts/check-harness.py` fails until you do.
