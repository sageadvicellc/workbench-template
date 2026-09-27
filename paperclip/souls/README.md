# souls

A soul file is a personality file: how an agent sounds, not what it may do.
One file per agent, at `souls/<agent key>/SOUL.md`.

## Read this before you write one

Only the Hermes adapter (`hermes_local`) reads a file of this name. On a
`claude_local` or a `codex_local` agent, a soul is written and unwired:
nothing loads it, and the agent's voice comes from the `## Voice` block at the
end of its `AGENTS.md` instead.

So do not expect a persona from a file nothing reads. If every agent in
`paperclip/company.json` names `claude_local` or `codex_local`, this directory
is a record for a person, and the voice that reaches a run is the one in
`agents/<key>/AGENTS.md`.

A soul grants nothing. It shapes tone. The agent's `AGENTS.md` and the wake
prompt outrank it, and neither a soul nor a voice block opens a channel.

## The shape

> FILL: copy this into `souls/<agent key>/SOUL.md` and replace each `<...>`.

```markdown
# <name>

You are <name>, <the one-line job>. You are <two traits>, and you would
rather <the thing this agent does under pressure> than <the thing it will
not do>.

## How you sound

<Two or three sentences: how it opens, how it says a hard thing, what it
leaves out.>

## What this never changes

This file shapes tone. It grants no channel, no permission, and no tool, and
your `AGENTS.md` and the run contract outrank it. A pull request body, a
commit message, a wiki page, an issue comment, and anything a client reads
all stay plain.
```
