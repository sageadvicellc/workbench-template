---
type: index
updated: 2026-09-25
---

# scripts

The flat home for everything executable that is not part of a skill or a
project repo.

A harness is the program that runs the agent loop and reads these files. No
script here names one. A path, a filename, or a setting that belongs to one
harness lives in that harness's adapter, under `adapters/`.

`central-context/` holds no code, by rule. When a check there needs to run
rather than be read, it lives here and `central-context/AGENTS.md` names it by
path.

A script that belongs to one skill stays with that skill, under
`wiki/skills/<name>/`. A script that belongs to one project stays in that
project's repo. Everything else is here.

| Script | Does | Run from |
|---|---|---|
| `bootstrap.py` | Sets this workbench up on a new Mac, or checks one. One step per thing to check; fixes what it safely can and prints the commands for the rest | The workbench root, through its entry point: `./bootstrap.sh`, or `./bootstrap.sh --check` to change nothing |
| `bootstrap.settings.json` | Data, not a script. Every value particular to one practice that `bootstrap.py` needs: paths, package lists, version minimums, repositories, packs, launchd agents. Tracked, at the workbench root | Read by `bootstrap.py` |
| `check-skills.py` | Checks skill frontmatter under `wiki/skills/` | The workbench root: `python3 scripts/check-skills.py` |
| `check-open-items.py` | Checks the `open_items` frontmatter of the context files | The workbench root: `python3 scripts/check-open-items.py` |
| `open-items-files.txt` | Data, not a script. The context files `check-open-items.py` reads by default | Read by `check-open-items.py` |
| `sync-harness.py` | Generates, per adapter manifest, the MCP tables a harness reads in its own format, from `.mcp.json` | The workbench root: `python3 scripts/sync-harness.py`, or `--check` to report and write nothing |
| `check-harness.py` | Proves the wiring: every declared symlink, every skill reachable through it, every generated file current, no harness named in the neutral core, and the entrypoint under its size cap | The workbench root: `python3 scripts/check-harness.py` |
| `paperclip-apply.py` | Makes a live Paperclip company match `paperclip/company.json`: the company flags, the instance switches, the labels, the org chart, the run caps, each agent's adapter, heartbeat, permissions, wake prompt and `AGENTS.md`, and each pipeline, routine and goal. Compares before it writes, so a rerun after a failure plans only what is left. Prints a plan and changes nothing without `--apply` | The workbench root: `python3 scripts/paperclip-apply.py` |
| `paperclip-watchdog.py` | The one automated stop on a Paperclip team. Pauses an agent at its run cap or after a burst of authentication failures, holds the assignment gate, starts board-approved work, parks work no person asked for, guards against a cascade of agent-made issues, and swaps a failing lead to its standby twin. Calls no model | The workbench root: `python3 scripts/paperclip-watchdog.py --dry-run` |
| `paperclip-new-org.py` | Starts a second Paperclip company from an overlay under `paperclip/orgs/`: creates the company, writes its id back into the overlay, runs the apply, records each hired agent's id, and prints that company's watchdog plist. Changes nothing without `--apply` | The workbench root: `python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json` |
| `paperclip-watchdog.plist.template` | Data, not a script. The launchd agent that runs the watchdog every five minutes for a workbench with one company. Holds two substitution markers, the label prefix and the workbench path | Rendered by `paperclip-new-org.py`'s `render_watchdog_template`, then installed by hand |
| `usage-value.py` | What this workbench's model use would cost at API list prices, by day, by source and by model, against a plan price. Reads transcripts only; changes nothing | The workbench root: `python3 scripts/usage-value.py --root <transcripts>` |
| `paperclip_lib.py` | The config loader, the overlay merge, the run-cap validator, the launchd label prefix loader, and the HTTP client the Paperclip scripts share | Imported, not run |
| `paperclip/api-prices.json` | Data, not a script. Model list prices per million tokens, with the source URL and the date they were read, and one plan price per provider. Names no account, key or organisation | Read by `usage-value.py` |

## bootstrap.py

A new machine needs a dozen things installed, signed into, and switched on
before any work runs here. This is the one command that says which of them are
done. `./bootstrap.sh` is the entry point: it proves the Xcode Command Line
Tools are there, because Python arrives with them, then runs this script on
`/usr/bin/python3`. The script itself imports nothing outside the standard
library, so it runs on a Mac nobody has set up yet.

Each step checks one thing and returns one status. A step this script can fix
safely, such as a `git config` or an install command, it fixes and rechecks. A
step that needs a person, such as a sign-in or an interactive installer, prints
the exact commands and waits for the next run. Every step is safe to run twice.
A step whose prerequisite did not pass is `blocked` and is not judged.

    ./bootstrap.sh              # check each step and fix what it can
    ./bootstrap.sh --check      # check only; change nothing
    ./bootstrap.sh --json       # the same report as JSON, for an agent
    ./bootstrap.sh --only node,repos
    ./bootstrap.sh --yes        # do not ask before running the settings commands

A fix runs commands that `bootstrap.settings.json` supplies, whole argument
vectors read from a file. No shell is involved, so this is not an injection
path. The exposure is plainer: a reader clones a derived workbench, runs one
command, and it executes configuration they have not read. So before the first
command of a run, the script prints every one of those vectors and asks for a
yes. Answer no and nothing runs, and every step that wanted a command reports
`failed`. `--yes` answers yes without asking, for an unattended run; asking is
the default. `--check` never asks, because it never runs anything.

A generated launchd plist is written at mode 600, readable only by its owner,
and its label may hold only letters, digits, a dot, an underscore, and a hyphen.
The label becomes a file name under `~/Library/LaunchAgents`, so a label with a
`/` or a `..` in it is refused by name rather than joined into a path. The
Paperclip API address in `paperclip.api` must be `http` or `https`, because
`urlopen` honours `file://` and `ftp://` too.

The seven statuses are `ok`, `fixed`, `fixable`, `manual`, `blocked`, `failed`,
and `skipped`. The exit code is 1 when any step is `manual`, `fixable`,
`failed`, or `blocked`, and 0 otherwise.

The steps, in order, and what each one checks:

| Step | Checks |
|---|---|
| `xcode-clt` | `xcode-select -p` answers, so the Command Line Tools are installed |
| `homebrew` | `brew` is on the PATH |
| `brew-packages` | every package in `brew_packages` is installed |
| `node` | `node --version` is at least `node_min` |
| `agent-cli` | the command in `agent_cli.command` answers, and its version is at least `agent_cli.min_version` |
| `gh-auth` | `gh auth status` reports a sign-in |
| `git-hooks` | this clone's `core.hooksPath` is `.githooks`, which cloning does not carry |
| `repos` | every directory in `repos` exists, and clones the ones that do not |
| `packs` | every entry in `packs.install` appears in the pack list, and adds each marketplace first |
| `cli-tools` | every `cli_tools` entry's `name` is on the PATH |
| `paperclip-cli` | `paperclipai` answers, at the version in `paperclip.version` |
| `paperclip-server` | `paperclip.api` answers on loopback |
| `paperclip-company` | one config under `paperclip/` names a company the server knows |
| `watchdog` | a launchd watchdog is loaded for each live company, labelled with `launchd_label_prefix` |
| `launch-agents` | every `launch_agents` label is loaded, writing its plist template with this checkout's path in place of `workbench_path_in_templates` |
| `review-webhook` | the file at `review_webhook.path` exists. It never prints the URL |
| `always-on` | `pmset -g` reports `sleep 0`, because a Mac that sleeps stops every agent run |

### What `skipped` means

`skipped` is the status for a step this workbench has not configured yet. A
setting that still holds an angle-bracket placeholder, such as `<x.y.z>`, or a
list that is empty, makes its step `skipped`, and the detail names the settings
key to fill in. A `skipped` step judges nothing: it blocks no step that needs
it, and it never makes the exit code non-zero on its own. The three Paperclip
steps and the watchdog are `skipped` whenever `paperclip.enabled` is false. A
step whose plist template, sibling script, or `paperclip/` directory is absent
is `skipped` too, with the path in the detail, rather than raising.

The text report ends with one line naming every settings key still holding a
placeholder, so a single run tells a person everything left to fill in. The
JSON report carries the same list under `placeholders`, beside a `summary` count
per status.

### bootstrap.settings.json

`bootstrap.settings.json`, at the workbench root, is the only place a value
particular to one practice belongs. Paths, package lists, version minimums,
repository remotes, pack names, marketplace names, launchd labels, and the
webhook path all live there. None of them belongs in `bootstrap.py`, which is
why the script names no harness, no repository, and no absolute home path: the
command it runs and the arguments it passes come from the file.

Two conventions bind the file. `{name}` inside a `packs` argument list is
substituted with the marketplace or pack name being added or installed. A
`repos` entry's `path` is relative to the workbench root unless it starts with
`~`, which resolves under the home directory, or `/`, which is taken as is. The
same rule applies to `review_webhook.path` and to each `launch_agents`
`template`.

The file ships fully unconfigured, so a fresh clone reports every configurable
step as `skipped` and nothing else. Fill it in during setup.

`launchd_label_prefix` is the reverse-DNS prefix every launchd label here is
built from, such as `org.example.workbench`. A label prefix names a practice, so
it lives here and never in a script. Three things read it: the `watchdog` step
above, `paperclip-new-org.py`, and `paperclip-watchdog.plist.template`. While it
still holds `<reverse.dns.prefix>`, the `watchdog` step is `skipped` and the two
Paperclip callers refuse with an error naming the key.

## paperclip-apply.py

The tracked files under `paperclip/` are the source of truth for the team. This
script reads the live company, prints every difference, and sends nothing unless
`--apply` is given.

    python3 scripts/paperclip-apply.py                              # dry run
    python3 scripts/paperclip-apply.py --apply                      # send it
    python3 scripts/paperclip-apply.py --config paperclip/orgs/<name>.json
    python3 scripts/paperclip-apply.py --show-bodies                # print each request body

**It compares before it writes.** Every action exists because a desired value
and a live value differ, so an in-sync company is a no-op even with `--apply`,
and a run that fails part way is safe to rerun: the rerun plans only what did
not land. A failure names how many changes went out before it.

Five behaviours are worth knowing before the first run.

- **A hire goes through board approval.** With
  `company["requireBoardApprovalForNewAgents"]` on, even the board hires through
  `POST /api/companies/{id}/agent-hires`, so the script approves the hire it
  just created: running it with `--apply` *is* the board's approval. If the hire
  lands and the approval call fails, the error says so and names the agent to
  approve by hand.
- **A second pass sets what a hire cannot carry.** The server refuses a wake
  prompt on a new agent and gives a hire a default task-assign grant, so after
  every applied pass the script replans and sends the difference. The same pass
  fills in a `reportsTo` that named a manager hired moments earlier, creates a
  routine or goal whose assignee was hired in the first pass, and adds a new
  routine's schedule trigger.
- **An agent is matched by id, then by name.** Two live agents with one name is
  an error rather than a guess, because a name match could push one agent's
  config onto another.
- **The heartbeat ships off.** `defaults.runtimeConfig.heartbeat.enabled` is
  `false` and nothing here turns it on. A heartbeat timer wakes an idle agent on
  a clock with nothing asking for the work, which is an unbounded loop.
- **A pipeline that exists but does not match is reported, never silently
  accepted.** A half-built pipeline, an approver the server downgraded to "any
  human", or automation wired to the wrong agent each print as drift for a
  person to fix or archive. A drift note is never sent anywhere.

Two settings stay off by default, `applyAssignmentPolicy` and `applyPipelines`,
because each needs a proof run against a throwaway company first.

## paperclip-new-org.py

A second company, run by the same team, from an overlay under `paperclip/orgs/`.
An overlay names its base with `extends` and the new company in `company.name`.

    python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json                   # dry run
    python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json --apply
    python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json --watchdog-plist

**A live company with the overlay's name is an error, not a match.** Adopting a
company by name alone could configure the wrong one, and a rerun after a lost
write must not create a second. Set `companyId` by hand if the live company is
the right one.

**The overlay is patched from a fresh read and replaced atomically.** The read
happens after the network call, so an edit somebody made to the overlay while
the request was in flight survives; only the keys the patch sets are written,
and a crash mid-write leaves the old file rather than a torn one. Commit the
overlay after `--apply`: the ids it records are how the next apply finds the
same agents.

`--watchdog-plist` prints the launchd agent for this company, labelled
`<launchd_label_prefix>.paperclip-watchdog.<overlay stem>`, so every company on
one machine gets its own. `render_watchdog_template` renders the tracked
single-company template the same way, from the same prefix, which is why the
installed file and `bootstrap.py`'s `watchdog` step never disagree.

## paperclip-watchdog.py

The one automated stop. It calls no model: it reads the local Paperclip API,
decides, and writes only to `/api/` paths, so it can never be the thing that
spends a run. A pass with nothing to do costs under a second. Its module
docstring lists all seven duties; this section carries what a person setting it
up has to know.

    python3 scripts/paperclip-watchdog.py --dry-run   # print the plan, change nothing
    python3 scripts/paperclip-watchdog.py             # act and log

Run `paperclip-apply.py --apply` once first: the watchdog needs the
`scope-creep` label to exist. Each company keeps its own state file and log,
named in `watchdog.stateFile` and `watchdog.logFile`. Both must name a path
under this checkout: they are joined onto the repository root, and a `../` or an
absolute path in either would write outside it. The log is written at mode 600,
because it holds issue titles, agent names, and pause reasons.

An overlay's `extends` must name a file under the same `paperclip/` directory as
the overlay itself, and a chain that reaches a file twice is a named error
rather than a `RecursionError`.

**Three cautions, each learned the hard way.**

1. **No run cap may be `0`.** Every enforcement site tests a cap for
   truthiness, so a `0` reads as "no cap configured" and disables the breaker
   instead of stopping the agent, silently and with no warning. The caps are
   validated before they are read: a `0`, a `"60"`, a `60.0`, a negative, or a
   `true` is a clear error. No example, default, or template value may be `0`.
   Leave a cap out to mean uncapped; never write it as zero.
2. **A cap-paused agent never resumes on its own.** There is no new-day resume
   here. A per-agent cap stops one agent; an adapter's `harnessTotal` stops
   every agent on that adapter, and a fleet-total pause therefore stops the
   whole team and waits for a person. Resume from the Paperclip interface, or
   with that agent's resume route in the Paperclip API. Size `harnessTotal`
   knowing that.
3. **The heartbeat stays off.** A template that shipped an idle-run behaviour
   with a heartbeat timer on would ship an unbounded loop, so
   `defaults.runtimeConfig.heartbeat.enabled` is `false` in every example here
   and `paperclip-apply.py` never turns it on.

Two `watchdog` lists are empty by default and change nothing until they are set.
`leadKeys` names which agent keys are leads, which is what makes a lead's
delegation child exempt from the assignment gate and the scope-creep park.
`workerKeys` names which are workers, which is what pauses a worker that creates
an issue. A lead is never listed in `workerKeys`: a lead creating child issues is
the flow working as designed.

## usage-value.py

A subscription has no dollar figure per run. This puts one on them, for the
return on the plan: it reads agent transcripts, prices each assistant message by
its model, and totals by day, by source and by model.

    python3 scripts/usage-value.py --root <transcripts>
    python3 scripts/usage-value.py --root <transcripts> --since 2026-09-01
    python3 scripts/usage-value.py --root <transcripts> --subscription-usd 200
    python3 scripts/usage-value.py --root <transcripts> --json

`--root` is required and has no default, because a default would name one
harness's transcript directory and no script in this tree names a harness. It is
a directory of JSON Lines transcripts, read recursively, so a subagent's
transcript in a subfolder counts too.

A message logged more than once counts once, matched on its id and request id. A
source is `fleet` when a line's `entrypoint` is one of `FLEET_ENTRYPOINTS` and
`interactive` otherwise. A self-hosted model listed under `localModels` is
priced at the API model it stands in for and reported as money saved, apart from
the plan total. **A model the prices file does not list is never priced at
zero:** it is named with its output tokens, so a reader knows the total is
short.

Anything the run could not read is counted and named the same way, in the text
and under `skipped` in the JSON: `roots` for a root that is not a readable
directory, `files` for a transcript that raised on read, and `lines` for a line
that is not JSON. A mistyped `--root` used to read as a month with no usage.

`paperclip/api-prices.json` holds the figures, with `source`, `retrieved`, and a
plan price per provider. Every number there was read from the vendor's public
pricing page on the date the file records. It names no billing account, key or
organisation. Update it by reading those pages again and changing the
`retrieved` date in the same commit.

## check-skills.py

A harness skips a malformed skill file in silence, so this is the only thing
that reports one.

It checks every directory directly under `wiki/skills/`: that a `SKILL.md`
sits directly under `wiki/skills/<dir>/` and not deeper, that no skill
directory is empty, that `name` matches the directory and is lowercase-hyphen
and at most 64 characters, and that `description` is not empty. It also
reports a missing `wiki/skills/` at the checked root, so a run against the
wrong directory never reports a clean tree.

Every finding is a failure, and every failure is a defect. Fix the file. The
exit code is the failure count, capped at 125, which makes the script usable
as a pre-commit hook with no wrapper. Nothing calls it automatically yet.
Wiring it into one is a decision for this workbench; open an item in
`AGENTS.md` if you want it tracked.

### Exempting somebody else's skill

`THIRD_PARTY_SKILLS` in the script exempts an installed skill whose `name`
differs from the directory it was installed into. The set ships empty, so
nothing is exempt today. That is an exemption from a published standard, not
from a house convention: the Agent Skills specification,
`https://agentskills.io/specification`, read 2026-09-11, states the `name`
field "Must match the parent directory name". A listed skill does not conform.
A harness invokes an installed skill by its directory name, so it still loads,
and the exemption is a decision to tolerate a non-conforming file somebody else
wrote. Everything not listed there is checked, so a skill you wrote is never
skipped by forgetting to register it.

The same specification sets the other name rules the script enforces: 1 to 64
characters, lowercase alphanumeric and hyphens, no leading or trailing hyphen,
no consecutive hyphens. It also publishes a validator, `skills-ref validate`,
which checks a single skill and not the nesting or the tree shape this script
covers.

## check-open-items.py

An open item is a question nobody has settled, written into the `open_items`
frontmatter of a context file. This script is the one reader of that block.

One written form is accepted. It is the example block in the `Open items schema`
section of `central-context/AGENTS.md`, which is the authority on the six fields
and on what each one holds. `open_items:` sits at column 0 inside frontmatter,
an item opens at two spaces with `- id:`, the five other keys each sit on their
own line at four spaces in the schema's order, and the `item: >` paragraph sits
at six. Every other form is refused by name, never parsed and never guessed at.
A refusal names the path, the line, the shape found, and the edit that fixes it.
A refused item is dropped whole, so no file is ever half-read while it appears
read.

Three things it reports separately:

- **A failure** is a defect. A refused shape, a path it cannot read, or a file
  that declares `open_items:` and yields no item. Reading nothing is never a
  pass.
- **A question** blocks and says nothing about the file being wrong. There are
  two: no file read declares `open_items:` at all, which almost always means the
  paths are wrong, and an `open_items:` at column 0 outside frontmatter and
  outside a fenced code block, which the script does not read and cannot tell
  from a block somebody wrote in the wrong place.
- **A due item** is one whose `checked` date is older than the cutoff. Nobody has
  tested that claim since the date shown. `wiki-verify` re-tests it in a reading
  pass, so a due item never affects the exit code.

The exit code is the failures plus the questions, capped at 125, so it can run
as a pre-commit hook with no wrapper. Nothing calls it automatically yet.

**On a clean tree it reports 0 failures and 0 questions, and it exits 0.** Any
finding on a tree nobody has just edited is worth reading.

The script ignores every line inside a fenced code block. A fenced example is
documentation, never a declaration. A fence that opens and never closes is a
failure naming the line it opened on, because every line below an open fence
is unread.

With no path argument the script reads the file list at
`scripts/open-items-files.txt`, one path per line. **An item in a file that list
does not name is invisible.** When you write an item into a file the list does
not name, add the line in the same commit. A listed path that no longer exists
is a failure. A path argument checks something else instead, and a directory
argument checks every `*.md` file below it. An entry below it that the
filesystem cannot describe, such as a broken symlink, is a failure too, and it
still counts as a file the run found.

Four options:

- `--findings-only` prints the findings and the counts, and holds back the item
  listing. Mechanical check 1 of `wiki/skills/wiki-verify/SKILL.md` calls the
  script this way.
- `--stale-days N` sets the due window, in days since `checked`. Default 14.
- `--today YYYY-MM-DD` sets the run date, for a test.
- `--root PATH` sets the path findings print relative to.

## sync-harness.py

Every path, format identifier and harness fact it uses comes from
`adapters/<id>/wiring.json`, so the script names no harness. A manifest's
`mcp` block names a format, the source `.mcp.json`, the path to write, and a
hand-edited head to put first. That is the only block it renders. The
generated files are committed. Run the script after any edit to `.mcp.json`,
or to a head file, and commit what it wrote.

`--check` writes nothing and exits 1 with one line per file that is missing or
differs from its source. Exit 2 is an input the script cannot use, named on
stderr: an unreadable manifest, a format nobody registered, or an MCP server
the target format cannot express. It refuses rather than approximates, because
a server rendered differently from its source is a server that works on one
harness and silently not the other.

## check-harness.py

The one command that says whether a clone is wired. One line per failure,
then `N failure(s)`, and the exit code is N capped at 125. It reads the same
manifests as `sync-harness.py`, so an adapter is checked the moment its
manifest exists.

The harness-name scan reads `adapters/harness-names.txt`, strips every
`adapters/<id>/...` path token from a line, and reports every remaining match
in the nine permitted paths of the neutral core, `wiki/` among them, so the
pack's skills are scanned too. Zero on a clean tree is the right answer: every
sentence in the core that reaches an adapter carries a path and no harness
name. A plain file where a symlink should be gets the Windows fix in its
message.

Reachability is proved per link: for any link whose destination holds
`<dir>/SKILL.md` files, each of those files must be readable through the link.
A link an adapter points at `wiki/skills` is proved the same way as one
pointed anywhere else.

It proves wiring, not behaviour. Whether a harness loads the entrypoint, loads
a skill, or completes a wiki operation is the acceptance test below, which does
not exist yet.

## Tests

`tests/` holds the tests for every script here, one file per script. Run them
from the workbench root with `python3 -m unittest discover -s scripts/tests`.
What each file covers is described in its script's module docstring and above.

## Not built yet

`harness-acceptance.py` does not exist on disk on 2026-09-12, so this file does
not say what it does. Add its table row when it lands, written from the script
itself.

One thing about the acceptance test is settled and belongs here, because a
reader who runs it will see failures and wonder whether the suite is broken. It
proves a harness by checking three surfaces: the entrypoint loads without being
asked, one skill loads on demand, and one wiki operation completes end to end.
Two runs are expected to fail, and both exist to show that the test can detect
a broken tree.

1. Run against a harness identifier with no adapter installed, the test fails
   at the first surface and names the missing adapter.
2. Run with the skill discovery path removed, the test passes surfaces 1 and 3
   and fails surface 2.

The workbench's specification requires both to be stated as expected behaviour
in the test's own documentation.
