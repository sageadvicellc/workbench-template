# paperclip

This directory is the source of truth for the Paperclip company this workbench
drives. The live server holds a copy, and `scripts/paperclip-apply.py` makes
the copy match these files. Edit here, then apply. An edit made in the
Paperclip interface is overwritten by the next apply.

It ships as a scaffold: the shape, with every identifier a placeholder.
`prompts/setup-paperclip.md` fills it in. Find every unfilled spot with:

```bash
grep -rn '^ *> FILL:' --include='*.md' .
```

## What each file does

| File | Holds |
|---|---|
| `company.json` | The company id, the safety switches, the labels, the adapter and heartbeat defaults, the run caps, and one entry per agent: runtime, model, turn cap, timeout, daily run cap, and permissions |
| `wake-prompt.md` | The run contract: a shared part, the hand-off, the idea bullets, a lead contract, and how a runtime runs a named subagent. It replaces the adapter's default wake prompt, and it is sent to the server word for word |
| `agents/<key>/AGENTS.md` | One instructions file per agent. `company.json` names the path in that agent's `instructionsFile` |
| `subagents/<name>.md` | One spec per named subagent. A lead passes the whole file to its runtime's subagent mechanism |
| `souls/<key>/SOUL.md` | One personality file per agent. Only the Hermes adapter reads a file of this name; `souls/README.md` says what that means |
| `orgs/<name>.json` | An overlay that runs this same team against a second company |
| `ideas.md` | The idea ledger: what a run that woke with no issue may do, and how an idea reaches the owner |
| `api-prices.json` | Price per million tokens, per model, for `scripts/usage-value.py` |

## The order a setup pass fills them in

1. `company.json`, from the answers in stages 0 and 1 of the setup prompt.
2. `wake-prompt.md`, with the owner's name, the board user id, and the role
   and skill roots of the packs installed here.
3. `agents/chief-of-staff/AGENTS.md`, then one copy of `agents/lead/AGENTS.md`
   per lead.
4. `subagents/builder.md` and `subagents/reviewer.md`, one copy per subagent
   each lead runs.
5. `souls/`, only if an agent runs on Hermes.
6. `ideas.md`, if the owner wants an idea ledger at all. Delete it and the
   wake prompt's idea bullets together if they do not.
7. `orgs/example.json`, only when a second company is needed.

## The gate between a scope and a build

Nothing an agent produces starts work. One gate stands between a scope and a
build, and only a person passes it:

1. The owner creates a ticket, assigns the chief of staff, and sets `todo`.
2. The chief of staff writes one `scope` document, raises one approval card,
   and hands the ticket back in `in_review`.
3. The owner approves the card. The watchdog then assigns the lead the scope
   names and sets the ticket `todo`. A rejection returns the ticket to the
   chief of staff with the reason.
4. The lead delivers inside one run and hands the ticket back.
5. The owner sets `done`, or comments for a revision.

`company.json` caps `request_confirmation` at `human_only`, so no agent can
resolve that card. An agent that assigns work to another agent is paused by
the watchdog and the ticket comes back to the owner.

## Three things that bite

**A run cap of `0` enforces nothing.** Every enforcement site guards on
truthiness, so a cap of `0` reads as "no cap configured" and disables the
breaker instead of stopping the agent, silently. `scripts/paperclip_lib.py`
refuses one at apply time. Never write `0`, `null`, or `""` as a cap: leave
the key out if you mean uncapped, and write a positive whole number if you
mean capped.

**A cap-paused agent does not resume on a new day.** The watchdog pauses at
the cap and never unpauses. A person resumes the agent in the Paperclip
interface. So a cap set fleet-wide can stop every agent at once, and the fleet
waits for a person.

**The idea ledger's three caps are self-policed.** One move a run, three ideas
below `ready`, one proposal a week: nothing in the server enforces any of
them. That is why `defaults.runtimeConfig.heartbeat.enabled` must stay
`false`. A timer would fire idle runs on a schedule and multiply an unenforced
cap.

## Change the team

1. Edit a file here on a branch.
2. Run `python3 scripts/paperclip-apply.py` and read the plan.
3. Run `python3 scripts/paperclip-apply.py --apply`.
4. If the run created an agent, copy its new id into `company.json`.

## A second company

An overlay under `orgs/` runs the same team against another company. It names
`company.json` in `extends`, and it sets only what differs: the company name,
the run caps, the goals, the watchdog files, and each agent's id under
`agentOverrides`. Objects merge into the base key by key. Lists replace the
base's. An overlay's `extraAgents` is a list of whole agent entries that exist
only in that company.

```bash
python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json            # plan
python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json --apply    # create and hire
```

The script writes the company id and each agent id back into the overlay.
Commit the overlay afterwards. To change that company later, run
`scripts/paperclip-apply.py --config paperclip/orgs/<name>.json`.

Each company needs its own watchdog.
`paperclip-new-org.py <overlay> --watchdog-plist` prints a launchd entry for
one.

## Runtime state

`.paperclip/` at the workbench root is a different thing. It holds untracked
runtime state: worktrees, each agent's ledger, the watchdog log, and the
watchdog state file. Nothing there is a source of truth.
