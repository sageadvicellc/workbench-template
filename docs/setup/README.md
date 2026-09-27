# Setup runbooks

A runbook here is for the owner's own interactive session, not for an agent in
the Paperclip company. Each one changes something outside this repository: a
Discord server, a bot token, a plugin install, a network route. None of them
runs by itself.

Read them in this order. Stop where one says stop.

| Runbook | What it builds | Needs first |
|---|---|---|
| `discord-server-setup.md` | The server, its channels, its roles, and one maintenance bot | A Discord account |
| `discord-agent-bots.md` | One bot per lead, plus the system bot, and their tokens as company secrets | The server, and a Paperclip company |
| `discord-plugin-install.md` | The Paperclip Discord plugin, its configuration, and the review webhook | The bots and their secret IDs |
| `phone-access-tailscale.md` | A route from a phone to the Paperclip host | A running Paperclip instance |

`prompts/setup-paperclip.md` builds the company these runbooks talk to. Run it
first. The Discord layer is optional. A Paperclip company works without it, and
the owner then reads and answers in the Paperclip interface instead.

## The rule that shapes all four

No bot token reaches an agent's runtime. The owner's own sessions hold the
maintenance token. Every other token becomes a Paperclip company secret, and a
secret without a grant for an agent is refused to that agent. An agent that can
post to Discord can be told what to post by anything it reads, so the default is
that no agent holds a channel at all.

## Placeholders

Every value in angle brackets is yours to fill. A `> FILL:` line marks a
decision nobody has made yet. Find them all with:

```bash
grep -rn '^ *> FILL:' --include='*.md' docs/setup
```
