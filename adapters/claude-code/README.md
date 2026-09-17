# Claude Code adapter

Claude Code is the one harness in the candidate set that does not read
`AGENTS.md`, so the workbench root carries a symlink for it. This directory
holds the manifest that declares that wiring, and nothing else. Delete the
directory and the workbench still works on every other harness, because the
symlinks it declares are tracked in git and need no installer.

## Getting started on this harness

1. Clone the workbench and run the wiring check from its root:

   ```bash
   python3 scripts/check-harness.py
   ```

   `0 failure(s)` means every symlink this adapter declares is in place. On
   Windows, turn on Developer Mode or run as Administrator, which is what a
   symlink needs there, then clone with `git clone -c core.symlinks=true`.
   Never use a zip download, which flattens a symlink into a text file. The
   check names the fix if it finds one. The documented alternative on a
   machine that cannot make symlinks is a hand-written `CLAUDE.md` holding
   the line `@AGENTS.md` (`https://code.claude.com/docs/en/memory`, retrieved
   2026-09-11); the check then reports that file as not a symlink, and the
   role and skill links still need one.

2. Install the wiki pack, then the packs chosen in `prompts/setup.md` stage
   0. The wiki pack is declared by `.claude-plugin/marketplace.json` at the
   workbench root, so the repo is its own marketplace:

   ```bash
   claude plugin marketplace add <owner>/workbench-template
   claude plugin install wiki@workbench
   ```

   Replace `<owner>` with the GitHub owner of the clone's remote, or pass the
   local path (`claude plugin marketplace add .` from the root) to install
   from the checkout. Every other pack comes from its own marketplace, with
   the command its README gives; `README.md` at the root lists one working
   set under "Packs and plugins". `claude plugin install` "installs to user
   scope unless you pass `--scope`" and loads "the next time you start Claude
   Code" (`https://code.claude.com/docs/en/discover-plugins`, retrieved
   2026-09-12). A plugin that carries hooks or many skills costs tokens in
   every session it is enabled in; `claude plugin details <name>` reports the
   always-on cost, and `enabledPlugins` in a repository's
   `.claude/settings.json` enables it there and nowhere else.

3. Start a session at the workbench root:

   ```bash
   claude
   ```

   A session must start at the root, or the entrypoint does not load. See
   "The instruction filename and its load order" below.

4. Confirm the surfaces loaded. `/context` lists `CLAUDE.md` under memory
   files, and any roles a chosen pack ships under custom agents ("check that
   agents appear in `/context` under Custom Agents",
   `https://code.claude.com/docs/en/plugins`, retrieved 2026-09-12). `/plugin`
   lists every pack from step 2. The five wiki skills load on demand when a
   request matches a description; ask for a wiki lint to see one fire.

5. Paste `prompts/setup.md` into the session. It walks the specialisation
   pass and ends by running the checks above again.

## What this adapter declares

`wiring.json` beside this file names one symlink. `scripts/check-harness.py`
reads it and proves it exists and points where it says.

| Path | What it is | Source | Retrieved |
|---|---|---|---|
| `CLAUDE.md` | Symlink to `AGENTS.md`. The documentation states "Claude Code reads `CLAUDE.md`, not `AGENTS.md`" and gives `ln -s AGENTS.md CLAUDE.md` as the bridge when no harness-specific content is wanted | `https://code.claude.com/docs/en/memory` | 2026-09-11 |

Two more paths are this harness's and not declared in the manifest, because
they are plugin manifests and not wiring: `.claude-plugin/marketplace.json`
at the root declares the `wiki` pack, and `wiki/.claude-plugin/plugin.json`
is that pack's own manifest. `claude plugin validate .` checks both. Skills
and roles reach a session through installed packs, never through a symlink
into this tree, so `.claude/agents` and `.claude/skills` no longer exist.

Beside the symlink, `.claude/.gitignore` keeps the two files this
harness writes during a session out of every commit: `settings.local.json`,
documented as "You, in this one project only", and `scheduled_tasks.lock`,
which the documentation does not mention
(`https://code.claude.com/docs/en/settings`, retrieved 2026-09-11). It also
ignores `worktrees/`, which the harness creates under `.claude/` for an
isolated session. A nested ignore file can ignore paths inside its own
directory, so the root `.gitignore` in the neutral core stays free of any
harness name.

This adapter generates nothing and carries no mapping file. A role's model
or tools are set in the pack that ships the role, on that pack's terms.

MCP servers come from `.mcp.json` at the workbench root, which this harness
reads directly. It ships empty. Add a server there and every harness whose
adapter generates an MCP block picks it up on the next run of
`scripts/sync-harness.py`.

## Permissions

The template ships no permission rules, here or anywhere else in the tree. Every
prompt you get on a read-only command is your own machine asking you, and
answering it once or writing a rule that stops it asking is yours to decide. The
syntax for `allow`, `ask` and `deny`, and the file each rule belongs in, are at
`https://code.claude.com/docs/en/permissions` ("Configure permissions",
retrieved 2026-09-11). No example rule set appears here, because an example is a
posture with a disclaimer on it.

## The instruction filename and its load order

All of this is from `https://code.claude.com/docs/en/memory`, retrieved
2026-09-11.

The filename is `CLAUDE.md`. Four scopes load, in this order, from the broadest
to the most specific, so the most specific is read last:

1. Managed policy: `/Library/Application Support/ClaudeCode/CLAUDE.md` on
   macOS, `/etc/claude-code/CLAUDE.md` on Linux and WSL,
   `C:\Program Files\ClaudeCode\CLAUDE.md` on Windows.
2. User: `~/.claude/CLAUDE.md`.
3. Project: `./CLAUDE.md` or `./.claude/CLAUDE.md`.
4. Local: `./CLAUDE.local.md`.

Inside the directory tree, every `CLAUDE.md` from the filesystem root down to
the working directory loads at launch, ordered root first, and all of them are
concatenated rather than one overriding another. A `CLAUDE.md` in a
subdirectory below the working directory loads on demand, when the harness
reads a file in that directory. In one directory, `CLAUDE.local.md` is appended
after `CLAUDE.md`.

Two consequences for this workbench. A session must start at the workbench
root, or the root entrypoint does not load. And no file below the root, the
page schema included, is loaded at session start.

## The page schema arrives by reference, not by inclusion

The choice, settled by the owner on 2026-09-11: this adapter does not import
`central-context/AGENTS.md`. Its `CLAUDE.md` is a plain symlink to `AGENTS.md`
and carries nothing else. The session reads the page schema when the routing
row for the wiki's layout matches, which is the same mechanism every other
adapter uses.

The reason: this harness is the only one in the set with a documented import,
and using it would load the whole schema file into every session whether the
session touches the wiki or not. One mechanism across every adapter stops the
template privileging one harness.

The accepted risk: delivery now depends on the session following the routing
row. Nothing enforces it.

The mechanism this adapter declines is real and documented. A `CLAUDE.md` can
import with `@path/to/import`, imported files load into context at launch, and
imports recurse to a maximum depth of four hops
(`https://code.claude.com/docs/en/memory`, retrieved 2026-09-11). The support
matrix value for this adapter's schema column is therefore `reference`.

There is no `central-context/CLAUDE.md`. A per-directory instruction file for
one harness inside the knowledge base is the privilege this adapter exists to
remove. Do not add one.

## Model

Claude models only. Anthropic "doesn't support routing Claude Code to
non-Claude models through any gateway"
(`https://code.claude.com/docs/en/llm-gateway`, retrieved 2026-09-11). The
self-hosted half of the ask belongs to the other adapters.

This adapter ships no configuration file, so it names no model identifier at
all.

## Wiring check

`python3 scripts/check-harness.py` ran clean on this adapter's one symlink
on 2026-09-17, on the tree this file was committed in. That proves the wiring,
not the behaviour below.

## Acceptance surfaces

No run has happened on this adapter. Every cell below reads `not tested` and
stays that way until one does. A result is recorded from a transcript, never
inferred.

| Surface | What passes | Result |
|---|---|---|
| 1. The entrypoint loads unprompted | The root entrypoint's unique token appears in the first reply, with no tool call before it | not tested |
| 2. One role is dispatched | The probe role writes its file, its contents match exactly, and the main session never read the role file | not tested |
| 3. One skill loads on demand | The probe skill's token appears in the reply, and the main session never read its `SKILL.md` | not tested |
| 4. One real wiki operation | An ingest satisfies all five mechanical conditions: the raw file, the new page's frontmatter, resolving wikilinks, the index line, and the log line | not tested |

| Field | Value |
|---|---|
| Harness name | Claude Code |
| Harness version | not tested |
| Model identifier | not tested |
| Serving stack | not tested |
| Date of run | not tested |
| Tool calls in the transcript | not tested |
| Failed tool calls | not tested |
| Path each surface resolved from | not tested |

A pass another harness's configuration produced is not a pass. This harness's
user-scope files, `~/.claude/CLAUDE.md` and `~/.claude/skills/`, load whatever
the user holds, and an installed pack resolves from the plugin cache, so a run
records the absolute path each surface resolved from and names the pack a
skill or role came from.

## Removing the adapter

```bash
git rm CLAUDE.md .claude/.gitignore
git rm -r adapters/claude-code .claude-plugin wiki/.claude-plugin
```

The last two are the pack manifests this harness reads; the pack's skills
stay, because the routing rows in `AGENTS.md` reach them by path.

`scripts/check-harness.py` then has no manifest for this harness and checks
nothing for it.
