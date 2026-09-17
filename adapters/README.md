# Adapters

A harness is the program that runs the agent loop and reads this workbench's
files. The neutral core is every part of the workbench that names no harness.
Nine top-level paths are permitted in it and no others: the entrypoint
`AGENTS.md`, the knowledge base in `central-context/`, the wiki pack in
`wiki/`, plus `scripts/`, `prompts/`, `DECISIONS.md`, `SPEC.md`, `README.md`
and `.gitignore`. That is a list of what may be there, not a list of
what must be: the template ships no `SPEC.md`, and its absence is not a defect.
An adapter is one directory here that holds the wiring for one harness and
nothing else.

The wiring itself is tracked in git, outside the nine paths: the symlinks each
adapter's `wiring.json` declares, the files `scripts/sync-harness.py`
generates from the core, `.mcp.json`, the one hand-edited source of MCP
servers, and the pack manifests a harness installs the wiki pack from, which
sit in that harness's own dot-directory at the root and inside `wiki/`. A
harness's own dot-directory is not the neutral core, so a symlink, a
generated file, or a manifest there names nothing the core may not name. Every one of
those paths is owned by an adapter, is never hand-edited except `.mcp.json`,
and is checked by `python3 scripts/check-harness.py`. Settled by the owner on
2026-09-12, in place of a per-harness installer: a clone works with no step
between clone and session, and a generated file that is committed can be
proved current, which an installer's output cannot.

One routing row in `AGENTS.md` points at this file, and one paragraph in
`README.md` describes the adapter system. Neither is an exception to a rule, and
neither is a budget anybody has to stay inside. A neutral-core file may name the
`adapters/` path, and any path below it, as often as it needs to: a path
reference tells a reader where the wiring lives, which is the opposite of
carrying the wiring. Nothing counts those references. On 2026-09-12 the neutral
core mentioned an adapter on 40 lines, 24 of them in `prompts/setup.md`, and that
is a reading rather than a limit.

What a neutral-core file may not do is name a harness. `scripts/check-harness.py`
is that check: it reads the patterns in `adapters/harness-names.txt`, strips
every `adapters/<id>/...` path token from a line, and fails on any match in
the nine paths. On this tree on 2026-09-17 it reported `0 failure(s)`. Item 8
of "Adding an adapter" below says how to extend the pattern.

A criterion number below is provenance and not a reading list. This workbench
was built against a written specification in the tree it was generalised from,
under the heading "Make workbench-template harness-neutral". The template ships
no `SPEC.md` and a clone gets no copy of that file, confirmed by `ls SPEC.md` on
2026-09-12. Every rule a criterion number sits beside is stated here in full, so
nothing in this file waits on a file you do not have.

## What an adapter may hold

One adapter is one directory, `adapters/<harness-id>/`, where `<harness-id>` is
lowercase letters, digits and single hyphens. It holds at most these three
kinds of file and no fourth kind. Only `README.md` is required. A kind that is
absent is not a defect.

| Kind | File |
|---|---|
| (a) | `wiring.json`, the manifest that declares the discovery symlinks the harness documents and, where the harness needs it, the MCP format and path to generate |
| (b) | One configuration head in the harness's own format, hand-edited here. The generated configuration file at the harness's path is this head plus the MCP tables rendered from `.mcp.json` |
| (c) | A `README.md`, which opens with how to install the wiki pack and any chosen pack on this harness |

Roles and skills are not an adapter's to carry or generate. They arrive in
packs, and a pack that supports a harness ships that harness's manifest and
role format itself.

## What an adapter may not hold

- No rule from the always-on list in `AGENTS.md`, and no writing standard.
- No wiki content, no copy of `AGENTS.md`, no copy of any `SKILL.md` body.
- No role instruction prose, and no skill body. Both belong to a pack.
- No API key.
- No permission rule. This template ships none, in the neutral core and in
  every adapter, so every approval prompt a colleague sees is their own machine
  asking them. An adapter `README.md` names its harness's permissions
  documentation by URL and retrieval date instead, and ships no example rule
  set.
- No model identifier, except in exactly two places: the configuration head
  (b) and the dated run record in `README.md`. The manifest carries none, and
  the neutral core carries none anywhere. A role's model is pinned in the pack
  that ships the role.

An adapter `README.md` records, per surface, what was run and what happened:
the harness name and version, the model identifier, the serving stack, the
date, the result, and a source URL with a retrieval date for every
configuration surface the adapter uses. A surface with no run reads `not
tested` in that record.

## The four acceptance surfaces

A harness counts as working when all four of these work on it. The fourth
exists because running the wiki is the point of this workbench. A harness that
reads every file and cannot complete an ingest has proved nothing useful.

| Surface | What passes |
|---|---|
| 1. The entrypoint loads unprompted | The root `AGENTS.md` carries a token that appears in no other file. The first prompt asks for it. The exact token appears in the reply, and the transcript shows no tool call before that reply |
| 2. One role is dispatched | A probe role's only instruction is to write one named file holding a second token. The file exists, its contents equal the expected string exactly, and the transcript shows no read of the probe role file by the main session |
| 3. One skill loads on demand | A probe skill carries a third token, and its description matches one prompt that never names the file. The token appears in the reply, and the transcript shows no read of the probe `SKILL.md` by the main session |
| 4. One real wiki operation | An ingest satisfies five mechanical conditions: the raw file exists at `central-context/raw/sources/<date>-<slug>.<ext>` and is byte-identical to the fixture, at least one new page under `central-context/wiki/domains/` carries `type`, `status`, `created`, `updated` and a `sources` entry naming that raw path, every `[[wikilink]]` in the new page resolves to exactly one file under `central-context/wiki/`, `index.md` gained a line naming the new page, and `log.md` gained exactly one line in the ingest format |

A harness with no skill support still runs every wiki operation, because every
routing row in `AGENTS.md` that names a wiki skill also gives that skill's
file path under `wiki/skills/`. A harness with no pack support gets nothing
else this tree does not carry, and says so: a pack chosen at setup that the
harness cannot install is recorded as such in the setup report. A harness
with neither degrades to the entrypoint, the knowledge base and `prompts/`.

Degrading is never silent. A surface an adapter cannot deliver is recorded in
the matrix below with its reason. Where a vendor's documentation is silent, the
cell reads `not documented` and never `not supported`.

## Support matrix

The columns take three different value sets, and reading one set over another
column is how a check ends up flagging a correct cell.

- **A surface column**, 1 to 4, reads `verified YYYY-MM-DD`, `not supported`,
  `not documented` with a source URL and retrieval date, `not tested`, or
  `no adapter`. Those five and nothing else.
- **The schema column** names a mechanism instead of a result, so it reads
  `inclusion`, `reference` or `restatement`, defined below the table. Where no
  adapter exists there is no mechanism to name and the cell reads `no adapter`.
  It never reads `verified`, because choosing a mechanism is a design decision
  and not a run.
- **The model and version columns** carry an identifier, or `not tested` where no
  run has happened. A model cell may state a constraint instead where the harness
  accepts only one vendor's models, which note 1 below records for the one row
  that does it.
- **The wiring column** reads `checked YYYY-MM-DD`, the date
  `scripts/check-harness.py` last reported `0 failure(s)` on that adapter's
  declarations, or `no adapter`. It is a check of files on disk, never of
  behaviour, which is why it sits apart from the four surfaces.

No cell is blank and no cell is inferred.

`no adapter` is not a synonym for `not tested`. Both definitions belong to the
surface columns, 1 to 4, and to no other column. There, `no adapter` means no
adapter exists for that harness in this tree, and `not tested` means an adapter
exists and nobody has run it. A row only moves off `no adapter` when somebody
builds the adapter and runs the test. The model and version columns read
`not tested` wherever no run has produced a value, adapter or no adapter, which
is why every `no adapter` row below still carries it in those two.

| Harness | Wiring | 1. Entrypoint | 2. Role | 3. Skill | 4. Wiki op | Schema | Model | Version |
|---|---|---|---|---|---|---|---|---|
| Claude Code | checked 2026-09-12 | not tested | not tested | not tested | not tested | reference | Claude models only | not tested |
| Codex | checked 2026-09-12 | not tested | not tested | not tested | not tested | reference | not tested | not tested |
| DeepSeek Harness | no adapter | no adapter | no adapter | no adapter | no adapter | no adapter | not tested | not tested |
| opencode | no adapter | no adapter | no adapter | no adapter | no adapter | no adapter | not tested | not tested |
| goose | no adapter | no adapter | no adapter | no adapter | no adapter | no adapter | not tested | not tested |
| OpenHands | no adapter | no adapter | no adapter | no adapter | no adapter | no adapter | not tested | not tested |

The schema column states which mechanism delivers the wiki page schema in
`central-context/AGENTS.md` to the model. It takes one of three values.
`inclusion` means the harness loads the schema file itself through a documented
import. `reference` means the entrypoint names the schema file by path and the
session reads it before its first write to `central-context/`. `restatement`
means the adapter ships the schema rules in a file the harness loads at session
start. The neutral core guarantees `reference` on every harness, so the schema
reaches a harness with no import and no adapter.

Three things this matrix states about itself.

1. `adapters/claude-code/` holds a manifest and a `README.md`. Its one
   symlink is tracked and checked. No run has happened on it, so its four
   surfaces read `not tested`. It ships no configuration head, so it names
   no model identifier at all, and its model cell is a constraint rather
   than an identifier.
2. `adapters/codex/` holds a manifest, a configuration head and a
   `README.md`. Its one generated file is tracked and checked. No run has
   happened on it, so its four surfaces read `not tested`, and its schema
   column reads `reference` because the adapter imports nothing.
3. The four rows below Codex are harnesses this pass researched and did not
   adapt. Their rows stay because dated, retrieved evidence about a harness
   nobody has an adapter for is still what a colleague reads when choosing one.

## Evidence per row

Every claim below carries a source URL and a retrieval date. This landscape
moves fast. Treat each one as a snapshot of its date and re-retrieve it before
a build starts.

**Claude Code.** The only harness of these six that does not read `AGENTS.md`:
"Claude Code reads `CLAUDE.md`, not `AGENTS.md`", with two documented bridges,
an `@AGENTS.md` import and `ln -s AGENTS.md CLAUDE.md`
(`https://code.claude.com/docs/en/memory`, retrieved 2026-09-11). Files above
the working directory load at launch and subdirectory files load on demand when
the harness reads files there, so no file below the root loads at session start
(same URL and date). Claude models only: Anthropic "doesn't support routing
Claude Code to non-Claude models through any gateway"
(`https://code.claude.com/docs/en/llm-gateway`, retrieved 2026-09-11). The
self-hosted half of the ask therefore belongs to the other adapters. The rest
of this harness's surfaces, its permissions documentation and its schema choice
are in `adapters/claude-code/README.md`.

**Codex.** Reads `AGENTS.override.md`, then `AGENTS.md`, then any name in
`project_doc_fallback_filenames`, walking from the project root down to the
working directory and taking at most one file per directory. It "skips empty
files and stops adding files once the combined size reaches the limit defined
by `project_doc_max_bytes` (32 KiB by default)"
(`https://learn.chatgpt.com/docs/agent-configuration/agents-md`, retrieved
2026-09-11). That cap is why the root `AGENTS.md` and the chain of context
files above the working directory stay under 32,768 bytes. Skills: it scans
`$CWD/.agents/skills`, `$CWD/../.agents/skills`, `$REPO_ROOT/.agents/skills`,
`$HOME/.agents/skills`, `/etc/codex/skills` and its own bundled skills, and it
"supports symlinked skill folders and follows the symlink target when scanning
these locations". It loads only each skill's name and description first, then
the full `SKILL.md` when it selects that skill
(`https://learn.chatgpt.com/docs/build-skills`, retrieved 2026-09-11). Roles:
custom agents are standalone TOML files in `~/.codex/agents/` or
`.codex/agents/`, requiring `name`, `description` and `developer_instructions`,
with no tools field. "Subagents inherit your current sandbox policy" and
"Subagents inherit the permission mode selected beneath the composer", and a
single agent may set `sandbox_mode` explicitly
(`https://learn.chatgpt.com/docs/agent-configuration/subagents`, retrieved
2026-09-11). Model: the top-level `model` key, with `model_provider` naming a
provider id from `model_providers` and defaulting to `openai`, and
`[model_providers.<id>]` taking `base_url`, `name`, `wire_api` and `env_key`.
That page gives `responses` as the only supported `wire_api` value, which a
self-hosted endpoint has to serve
(`https://learn.chatgpt.com/docs/config-file/config-reference`, retrieved
2026-09-11).

One correction, and a builder needs it before writing `.codex/config.toml`.
The same page states that project-scoped configuration cannot override
machine-local provider keys, and it names `openai_base_url` and
`model_provider` among the keys Codex ignores in a project-local
`.codex/config.toml`. Those two belong in user-level `~/.codex/config.toml`
(same URL, retrieved 2026-09-11). A self-hosted run that changes only a
project-scoped file therefore changes nothing.

**DeepSeek Harness.** Entrypoint: it loads the user-global `$DSH_HOME/AGENTS.md`
and then every candidate file from the project root down to the working
directory, in broad-to-specific order, in one durable baseline message.
`instructionFileCandidates` defaults to `['AGENTS.md', 'CLAUDE.md']` and
`localInstructionFileCandidates` to `['AGENTS.local.md', 'CLAUDE.local.md']`.
The project root is marked by `.git` by default. Sibling files whose content
matches after trimming render once, so a `CLAUDE.md` symlinked to `AGENTS.md`
does not double the entrypoint
(`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/packages/context/agent-instructions/README.md`,
retrieved 2026-09-11). It loads no file below the working directory, so
`central-context/AGENTS.md` never loads by itself. Skills: six roots in rank
order, `<projectRoot>/.dsh/skills` at 100, `<projectRoot>/.agents/skills` at
200, `Config.customSkillDirs` at 300, `<dshHome>/skills` at 400,
`<agentsHome>/skills` at 500 and `Config.bundledSkillDir` at 600. It accepts
`<name>/SKILL.md` bundles and flat `<name>.md` files, and "Nested recursive
`**/SKILL.md` discovery is not supported". Whether it follows a symlinked skill
directory is **not documented** on that page
(`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/skills.md`,
retrieved 2026-09-11). Roles: **not documented** as a file surface. A subagent
provider is registered in code, and a start request carries optional model,
reasoning-effort and token overrides, each gated by a provider capability flag
(`https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/docs/subsystems/subagent.md`,
retrieved 2026-09-11 for `SPEC.md`, carried here on that date, not
re-retrieved). The nearest file-based surface is the preset plugin, which
mounts one preset `cordis.yml` under an agent scope. Whether that file can
declare a named role with its own instructions is not documented. Release
status: "DeepSeek Harness is in _developer preview_ and iterating rapidly.
**THERE WILL BE COMPATIBILITY-BREAKING CHANGES.**" The licence is MIT, the
install command is `npx @deepseek-ai/dsh web` and the CLI command is `dsh`
(`https://github.com/deepseek-ai/deepseek-harness`, retrieved 2026-09-11). The
newest release tag is `v0.1.5-rc.2`, dated 10 September and marked
pre-release, and every tag on that page is a pre-release, so there is no stable
version to pin
(`https://github.com/deepseek-ai/deepseek-harness/releases`, retrieved
2026-09-11). That undocumented role surface and that release status are the two
reasons this harness has no adapter here.

**opencode.** Entrypoint: it reads local `AGENTS.md` then `CLAUDE.md` by
walking up from the working directory, then a global
`~/.config/opencode/AGENTS.md`, then `~/.claude/CLAUDE.md` unless that is
disabled, and "The first matching file wins in each category". Extra
instruction files can be named in `opencode.json` under `instructions`
(`https://opencode.ai/docs/rules/`, retrieved 2026-09-11). Skills:
`.opencode/skills`, `~/.config/opencode/skills`, `.claude/skills`,
`~/.claude/skills`, `.agents/skills` and `~/.agents/skills`, each as
`<name>/SKILL.md`. It recognizes `name`, `description`, `license`,
`compatibility` and `metadata`, and ignores unknown frontmatter fields
(`https://opencode.ai/docs/skills/`, retrieved 2026-09-11). Roles: markdown
files in `~/.config/opencode/agents/` or `.opencode/agents/`, where the
filename becomes the agent id, carrying `description`, `mode: subagent`,
`model` in `provider/model-id` form, and `permission` keys valued `allow`,
`ask` or `deny` (`https://opencode.ai/docs/agents/`, retrieved 2026-09-11).

**goose.** Entrypoint: it looks for `AGENTS.md` then `.goosehints` at each
level, and `CONTEXT_FILE_NAMES` takes a JSON array of other names, defaulting
to `["AGENTS.md", ".goosehints"]`. It loads a nested file when it reads or
changes files in that directory, and the nested hints stay active for the rest
of the session
(`https://goose-docs.ai/docs/guides/context-engineering/using-goosehints/`,
retrieved 2026-09-11). Skills: `~/.agents/skills/` for every session,
`.agents/skills/` for the project, and `~/.agents/plugins/<plugin-name>/` for
plugin skills. It adds discovered skill names and descriptions to its
instructions when a session starts
(`https://goose-docs.ai/docs/guides/context-engineering/using-skills/`,
retrieved 2026-09-11). Roles: the equivalent is a recipe YAML file with `id`,
`version`, `title`, `description`, `instructions`, `activities`, `extensions`,
`parameters` and `prompt`, found through `GOOSE_RECIPE_PATH` or in the working
directory. A per-subagent `model` field is **not documented**
(`https://goose-docs.ai/docs/guides/context-engineering/subagents/`, retrieved
2026-09-11). Model: the Ollama provider defaults its host to
`localhost:11434`, and the OpenAI provider takes `OPENAI_HOST` and
`OPENAI_BASE_PATH`, which defaults to `v1/chat/completions`. It "extensively
uses tool calling, so models without it can only do chat completion", and it
"works best with Claude 4 models"
(`https://goose-docs.ai/docs/getting-started/providers`, retrieved
2026-09-11). A self-hosted model without tool calling therefore fails surfaces
2 and 4 on this harness before the adapter is at fault.

**OpenHands.** Entrypoint: `AGENTS.md` at the repository root is repository-wide
guidance and its "Full content is included in the initial system prompt". No
nested behaviour is documented. Skills load from
`.agents/skills/<skill-name>/SKILL.md`
(`https://docs.openhands.dev/overview/skills`, retrieved 2026-09-11). Roles:
**not documented** at that URL. Model: `LLM_MODEL` in the form
`openai/<served-model-name>`, `LLM_BASE_URL` pointing at the local server, and
`LLM_API_KEY`, which takes "any placeholder value (e.g. `dummy`, `local-llm`)
unless your server requires a real key", and for a vLLM or SGLang server "the
same key provided when starting the server". It "requires a large context size
to work properly", and the page sets that size per serving stack rather than
once: with Ollama, `OLLAMA_CONTEXT_LENGTH` goes to "at least 22000", because
"The default (4096) is way too small"; in LM Studio, "Context Length" goes to
"at least 22000 (for lower VRAM systems) or 32768 (recommended for better
performance)"; with Atomic Chat, "use at least ~22k tokens, and 32k+ when your
hardware allows"
(`https://docs.openhands.dev/openhands/usage/llms/local-llms`, retrieved
2026-09-12). The shorter form of that URL,
`https://docs.openhands.dev/usage/llms/local-llms`, answers 308 with that
location, so cite the long one.

One fact holds across all five harnesses that read `AGENTS.md`: each reads
`.agents/skills` at its own documented root. A later adapter for a harness
with no pack support can therefore declare one symlink, `.agents/skills`
pointing at `wiki/skills`, to reach the wiki skills without an install;
`scripts/check-harness.py` proves every `SKILL.md` reachable through it.
Only one of the five documents following a symlink there.

## What is not built

Three things this file names as absent rather than describing as working.

1. `scripts/harness-acceptance.py` does not exist. It is the runnable
   acceptance test for the four surfaces. Two scripts that earlier versions of
   this file named as absent now exist under other names:
   `scripts/sync-harness.py` generates the adapter MCP files, and
   `scripts/check-harness.py` runs the mechanical checks: the symlinks, the
   reachability of every skill through them, the currency of every generated
   file, the harness-name scan, and the entrypoint byte cap. The skills-in-prose
   assertion, the read-only description assertion, and the delete test are
   still run by hand, per item 8 below.
2. No adapter on disk names a model identifier, because no role lives in this
   tree to pin one to.
3. The stub check of criterion 63 has not been run. Nobody has added a stub
   adapter by following the section below, so no date and no name are recorded
   here. Until that run happens, the procedure below is unproven by anybody
   except its author.

Do not present a command line for the acceptance script as runnable. A step may
name the command it will use, as item 6 below does, on the one condition that
the same item opens by saying the script does not exist yet. Absence first,
command second: a reader who skims the first line of an item must not be able
to reach a command that would fail.

## Adding an adapter

Nine items, numbered so a later edit that drops one is visible. Follow them in
order. This section names no harness, because it is the same procedure for
every one.

Every section name the nine items cite is a heading in this file. Every path
they cite exists in a fresh clone, except two named as absent in the same item
that cites them: `scripts/harness-acceptance.py` in item 6, and `SPEC.md` in
item 8, which names it as a file this template does not ship and never as a
file to read.

1. **Know what you may ship.** The three kinds of file are in "What an adapter
   may hold" above: a `wiring.json` manifest, one configuration head, and a
   `README.md`. Only the `README.md` is required. Ship nothing of a fourth
   kind.
2. **Know what passes.** The four surfaces and the pass condition for each are
   in "The four acceptance surfaces" above. Read them before you write
   anything, because they are what the adapter exists to satisfy.
3. **Retrieve four configuration surfaces from the harness's own
   documentation, before you write anything.** The project instruction file and
   its load order. The skill discovery paths, and how a pack or plugin is
   installed. The role or subagent declaration, with its file format and
   required fields, so a pack author knows what to ship. The model provider,
   with its permission vocabulary.
4. **Record each one with a source URL and a retrieval date.** Where the
   documentation is silent, write `not documented` and never `not supported`.
   Silence is a gap in the record, not a statement about the harness.
5. **Declare the wiring, then generate it.** Write
   `adapters/<harness-id>/wiring.json`: a `links` object for every symlink the
   harness documents, and, where the harness needs it, an `mcp` block naming a
   format `scripts/sync-harness.py` registers, the source `.mcp.json`, the
   path to write, and the head file. Create the symlinks with
   `ln -s` and commit them. Then run `python3 scripts/sync-harness.py`, commit
   what it wrote, and run it again with `--check` to prove a clean tree
   produces no diff. A format the script does not register is exit 2 naming
   it; adding one is one rendering function and its tests.
6. **The acceptance test does not exist yet either, so no surface can be run.**
   `scripts/harness-acceptance.py` is absent, per the same section. Every surface
   cell of a new row therefore reads `not tested` until the script lands, and
   writing anything else there is a false claim. What the step becomes: run
   `python3 scripts/harness-acceptance.py <harness-id>`, which will exit non-zero
   on any failure and print one line per surface, reading `PASS` or `FAIL` with
   the surface number and the reason.
7. **Fill in your matrix row.** Add one row to the support matrix above with
   the values the run produced. A row moves off `no adapter` only on a run.
   Nothing in a surface cell is ever inferred from documentation, and a run
   that did not happen reads `not tested`.
8. **Keep the neutral core neutral.** Two rules, and learning them here is
   cheaper than learning them from a failing check.

   First, no file in the neutral core names a harness. Add one line to
   `adapters/harness-names.txt` for your harness's name and one for its
   discovery directory, as a regular expression, then run from the workbench
   root:

   ```bash
   python3 scripts/check-harness.py
   ```

   `0 failure(s)` is the pass. The script reads the nine permitted paths,
   skipping `SPEC.md` when this template ships none, strips every
   `adapters/<id>/...` path token from a line, and reports every remaining
   match with its file and line. Zero is the right answer and not a broken
   pattern: every sentence in the neutral core that reaches the adapters
   carries a path and no harness name, so the pattern has nothing to match.
   The same run also proves your symlinks, the reachability of every skill
   through them, the currency of every generated file, and the size of the
   entrypoint.

   Second, deleting this whole directory leaves a workbench that still passes
   its own checks: `python3 scripts/check-skills.py` reports zero failures,
   and `python3 scripts/check-harness.py` reports zero failures, because with
   no manifest there is nothing to declare.
9. **Start from retrieved evidence, not from a search.** For any harness in the
   matrix above that reads `no adapter`, "Evidence per row" above already holds
   the four surfaces of item 3, each with a source URL and the date it was
   retrieved. Read that before you search for anything. Then re-retrieve every
   URL you are going to rely on, because those dates are older than your clone
   and this landscape moves fast.
