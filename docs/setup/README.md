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

No bot token reaches an agent's runtime. That is an operating practice. Nothing
in this repository makes it true, and two things in these runbooks work against
it:

- `claude mcp add --scope local` binds a server to one account and one project
  directory. Every session that account starts in this directory gets that
  server, an agent's session included.
- The launch command puts the maintenance token into the child process's
  environment. Whatever starts that process holds the token.

Keep the rule anyway. It is the right rule, because anything an agent reads can
tell that agent what to post. So no agent holds a channel at all.

Following the practice looks like this. The owner's own sessions hold the
maintenance token. Every token lives in one env file, at mode 600 and outside
this repository, which the first runbook creates. No session that an agent runs
in sources that file.

When you add anything here, keep the rule. A token in a tracked file, in a
shell history, or in an agent's environment breaks it. One check here looks for
the first case: `scripts/tests/test_public_scrub.py` fails on a credential in
any tracked file. No check here reads a shell history, and no check here can
tell whether an agent's session sources the env file. Check both by hand.

## Placeholders

Every value in angle brackets is yours to fill. A `> FILL:` line marks a
decision nobody has made yet. Find them all with:

```bash
grep -rn '^ *> FILL:' --include='*.md' docs/setup
```
