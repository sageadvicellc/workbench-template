# Setup runbooks

A runbook here is for the owner's own interactive session, not for an agent.
Each one changes something outside this repository: a Discord server, a bot
token, a network route. None of them runs by itself.

Read them in this order. Stop where one says stop.

| Runbook | What it builds | Needs first |
|---|---|---|
| `discord-server-setup.md` | The server, its channels, its roles, one maintenance bot, and the env file that holds its token | A Discord account |
| `discord-agent-bots.md` | One bot per lead, plus the system bot, and their tokens in the same env file | The server and the env file from the first runbook |
| `phone-access-tailscale.md` | A route from a phone to a web service running on this machine | A web service on this machine, and a Tailscale account |

The Discord layer is optional. Nothing in this workbench depends on it, and the
owner then reads and answers wherever the agents already report. When a person
wants one place to read every agent, build it.

## The rule that shapes all three

No bot token reaches an agent's runtime. The owner's own sessions hold the
maintenance token. Every token lives in one env file, at mode 600 and outside
this repository, which the first runbook creates. No agent reads that file,
because no agent runs in a session that sources it. Anything an agent reads can
tell that agent what to post. So no agent holds a channel at all.

When you add anything here, keep that rule. A token in a tracked file, in a
shell history, or in an agent's environment breaks it, and nothing in this
repository checks for that.

## Placeholders

Every value in angle brackets is yours to fill. A `> FILL:` line marks a
decision nobody has made yet. Find them all with:

```bash
grep -rn '^ *> FILL:' --include='*.md' docs/setup
```
