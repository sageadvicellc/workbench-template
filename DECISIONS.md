---
type: log
updated: 2026-09-17
---
# DECISIONS.md

Append-only decision log. Newest entries at the bottom. Entries are never
edited or deleted. A reversal earns a new entry that supersedes the old one by
date.

The main session writes here, when the owner decides something. No role
does. The rule for what belongs here is in `AGENTS.md`.

An entry is warranted when a choice was settled that a future session would
otherwise re-litigate. Routine work does not earn one. An open question does
not either: that belongs in an `open_items` frontmatter block, which the main
session writes.

Format:

```
### YYYY-MM-DD · Short title
**Decided:** what was chosen, in one sentence.
**Instead of:** the alternatives that were on the table.
**Because:** the reasoning, in one or two sentences.
**Affects:** files or systems this changes.
```

---

### 2026-09-11 · The workbench starts from the template
**Decided:** This workbench is a clone of `workbench-template`, and the
template's example roles and skills stand until someone reads and replaces
them.
**Instead of:** writing the structure from scratch, or deleting the examples
before reading them.
**Because:** the shape is worth keeping and the opinions inside the examples
are not yet this workbench's. Keeping them visible makes the difference
findable. `AGENTS.md#workbench-not-specialised` tracks the pass that resolves
it.
**Affects:** `agents/`, `skills/`, `AGENTS.md`, `central-context/AGENTS.md`.

### 2026-09-12 · Harness wiring is tracked in git, not installed
**Decided:** The symlinks and generated files each harness discovers the
workbench through are committed. Each adapter declares them in a
`wiring.json` manifest, `scripts/sync-harness.py` generates the harness-format
copies from `agents/` and `.mcp.json`, and `scripts/check-harness.py` proves
every link and every copy. `.mcp.json` is the one hand-edited source of MCP
servers.
**Instead of:** a per-harness installer that creates untracked symlinks and
hides them in `.git/info/exclude`, which is what `adapters/claude-code/`
shipped until this date; or a neutral `mcp-servers.json` with `.mcp.json`
symlinked to it.
**Because:** a clone works with no step between clone and session, and a
generated file that is committed can be proved current, which an installer's
output cannot. The neutral-core rule is about what the core names, not what
the tree contains, and a harness's own dot-directory is not the core. The
symlinked-source variant depended on a harness following a symlinked MCP
file, which its documentation does not state.
**Affects:** `adapters/`, `scripts/sync-harness.py`, `scripts/check-harness.py`,
`.mcp.json`, every tracked symlink and generated file at the root,
`prompts/setup.md` stage 0.

### 2026-09-12 · The template ships six research roles and no delivery pipeline
**Decided:** The eight delivery roles are cut. Code and design work routes to
the `superpowers` plugin, installed per harness, and `AGENTS.md` says so under
"How work runs".
**Instead of:** keeping all fourteen roles as a harness-neutral fallback for a
harness with no plugin.
**Because:** the practice this template came from measured the roles at up to
33,000 preloaded tokens and cut them on 2026-09-12 after two design rounds
produced no application code. The plugin is on the marketplaces of both
harnesses this template has an adapter for, and a template that ships a
pipeline its source abandoned is a template that misleads.
**Affects:** `agents/`, `agents/README.md`, `AGENTS.md`, `prompts/setup.md`
stage 2, the routing table.

### 2026-09-17 · The template ships structure and one pack, and forces no other
**Decided:** The template ships the entrypoint, the knowledge base, the
checks, and one pack, `wiki/`, holding the five wiki skills and declared by a
marketplace manifest at the root. It ships no roles, no research skills, no
writing standard, and no code pipeline. `prompts/setup.md` asks, in stage 0,
which packs and plugins carry code, design, writing, and research, and
`README.md` lists one practice's working set as an example. This supersedes
the entry of 2026-09-12 that named a code plugin under "How work runs".
**Instead of:** Keeping the six research roles and the thirteen skills
vendored and drifting from their working copies; naming one code plugin as
the default; making the template depend on a private marketplace.
**Because:** The template is public and is meant for people at more than one
employer. Nothing it ships may be a package somebody has to accept, and the
wiki skills are the one thing the page schema cannot run without. Vendored
copies had drifted from their working copies by up to 93 lines per file in
five days, and every role change needed a generator, a mapping, and a check
that exist only to carry roles.
**Affects:** `wiki/`, the root marketplace manifest, `AGENTS.md`,
`README.md`, `prompts/setup.md`, `adapters/`, `scripts/check-skills.py`,
`scripts/sync-harness.py`, `scripts/check-harness.py`, the deleted `agents/`,
`skills/`, the generated role directory, and the three discovery symlinks.
