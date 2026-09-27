# Runbook: the agent bots

Builds one Discord application per lead, plus one system bot, and turns their
tokens into Paperclip company secrets. For the owner's own interactive session,
not for a Paperclip agent. The layout from `discord-server-setup.md` is already
in place.

## What this builds

One application per lead agent, and one more for the system:

| Application | Posts for | Channel | Role |
|---|---|---|---|
| `<lead name>` | That lead, and the named subagents it runs | That lead's channel | That lead's role |
| `<system name>` | Any agent not in the rows above | System, approvals | none |

> FILL: replace the two rows above with one row per lead, and name the system
> bot.

A named subagent has no bot of its own. Work assigned to a subagent posts
through its lead's bot, in a thread in the lead's channel. The plugin's agent
bot map carries that, as a list of extra agent IDs on each entry.

The system bot is the plugin's default bot. It posts Paperclip's system
notices, and it is the **only** bot that reads messages. It receives the
owner's replies, button clicks, and slash commands, and it joins the voice
channel if live voice is on. Every lead bot connects with message listening
off, so none of them needs a privileged intent.

## Before you start

- Create each application by hand in the developer portal. Discord has no
  public API that creates an application.
- Have the avatar images ready. Each goes on its application in step 2.
- Every token lives in the one env file from the server runbook, mode 600.
  Paperclip keeps an encrypted copy of each lead and system token as a company
  secret, because the plugin reads a token only through a secret reference.
  The maintenance bot's token never becomes a Paperclip secret.

## Steps

1. **Create the applications.** One per row of the table. Sign in with the
   account that owns the server.

2. **Set each bot.** On each application's Bot page:
   - Set the avatar.
   - Turn off Public Bot, so only you can invite it.
   - Decide the Message Content intent on the **system** application. Leave
     every privileged intent off on every lead application.

     Message Content is a privileged intent, and it is narrower than it looks.
     A button click and a slash command arrive as interactions and need no
     intent at all. A message that mentions the bot arrives with its content
     whether the intent is on or not. The intent buys one thing: the text of a
     free-form reply that does **not** mention the bot.

     So turn it on only if you want to reply without mentioning the bot. If
     every reply is a thread reply to the bot's own message, or mentions it,
     leave it off: that is the right call. With it on, the bot reads the
     content of every message in every channel it can see.

     Check the three rules in the paragraph above against Discord's own
     gateway intent documentation before you decide. They were written from a
     review, not from the documentation, and Discord has changed intent
     behaviour before.
   - Reset the token and copy it into the env file, under the name in step 5.
     Never paste a token into a chat session.

3. **Invite the lead bots.** For each lead application, copy its Application
   ID from the General Information page and open this URL with the ID in
   place:

   ```
   https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot&permissions=309237730368
   ```

   That integer grants seven permissions: `AddReactions`, `ViewChannel`,
   `SendMessages`, `EmbedLinks`, `ReadMessageHistory`, `CreatePublicThreads`,
   and `SendMessagesInThreads`. Check the bits in Discord's permission
   calculator before you use the number. Do not carry it from memory into a
   different permission set.

4. **Invite the system bot.** The same form, with one more scope and one more
   permission:

   ```
   https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot%20applications.commands&permissions=309238778944
   ```

   The `applications.commands` scope carries the slash command. The extra
   permission is `Connect`, so the bot can join the voice channel. Leave the
   scope and the extra bit off if you want neither.

5. **Add the tokens to the env file.** Beside the two lines the server runbook
   wrote, add one line per application:

   ```bash
   DISCORD_BOT_<LEAD>=<token>
   DISCORD_BOT_SYSTEM=<token>
   ```

6. **Sync the env file to Paperclip company secrets.** Run this in your own
   terminal. It creates each secret the first time and rotates it after, and
   it prints only the secret IDs. Run it again after every token reset.

   ```bash
   python3 - <<'PY'
   import json, os, pathlib, sys, urllib.parse, urllib.request

   LOOPBACK = {"127.0.0.1", "localhost", "::1"}

   company = os.environ["PAPERCLIP_COMPANY_ID"]
   base = os.environ.get("PAPERCLIP_API_URL", "http://127.0.0.1:3100").rstrip("/")
   # Every bot token below goes in the body of these requests. Over plain http
   # to anything but loopback, they cross the network in the clear. This is the
   # rule scripts/paperclip_lib.py already enforces on its own client.
   url = urllib.parse.urlparse(base)
   if url.scheme != "https" and url.hostname not in LOOPBACK:
       sys.exit(f"refusing to send tokens over plain http to {url.hostname}")
   if not base.endswith("/api"):
       base += "/api"
   env_path = pathlib.Path.home() / ".config" / os.environ["WORKBENCH_NAME"] / ".env"
   names = os.environ["DISCORD_BOT_NAMES"].split()
   token = os.environ.get("PAPERCLIP_BOARD_API_KEY")

   def unquote(value):
       # A shell env file may quote a value. `DISCORD_BOT_SYSTEM="tok"` would
       # otherwise store the quotes and fail later as a Discord auth error.
       value = value.strip()
       if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
           return value[1:-1]
       return value

   env = {}
   for line in env_path.read_text().splitlines():
       if "=" in line and not line.lstrip().startswith("#"):
           key, value = line.split("=", 1)
           env[key.strip()] = unquote(value)

   def call(method, path, body=None):
       headers = {"Content-Type": "application/json"}
       if token:
           headers["Authorization"] = f"Bearer {token}"
       request = urllib.request.Request(
           base + path,
           method=method,
           data=json.dumps(body).encode() if body is not None else None,
           headers=headers,
       )
       with urllib.request.urlopen(request) as response:
           return json.load(response)

   existing = {s["key"]: s["id"] for s in call("GET", f"/companies/{company}/secrets")}
   missing = []
   for name in names:
       value = env.get(f"DISCORD_BOT_{name.upper()}")
       if not value:
           missing.append(name)
           continue
       key = f"discord-bot-{name.lower()}"
       if key in existing:
           call("POST", f"/secrets/{existing[key]}/rotate", {"value": value})
           print(name, existing[key], "rotated")
       else:
           made = call("POST", f"/companies/{company}/secrets", {
               "name": f"Discord bot token, {name}",
               "key": key,
               "provider": "local_encrypted",
               "managedMode": "paperclip_managed",
               "value": value,
           })
           print(name, made["id"], "created")
   if missing:
       # A partial sync is not a success. A wrapper reads the exit code.
       sys.exit("missing from the env file: " + " ".join(missing))
   PY
   ```

   Set `PAPERCLIP_COMPANY_ID`, `WORKBENCH_NAME`, and `DISCORD_BOT_NAMES`
   before you run it. `DISCORD_BOT_NAMES` is a space-separated list, one name
   per application, matching the suffixes you used in step 5.

   Set `PAPERCLIP_BOARD_API_KEY` as well when the instance is not in a trusted
   loopback mode. Without it, an authenticated instance refuses every call
   above.

   The secrets carry no agent binding. An agent reads a secret only through
   `POST /api/agents/me/secrets/{key}/value`, and that route refuses any
   secret with no grant for that agent.

7. **Keep the Model Context Protocol server to its own token.** If the server
   runbook's launch command exported every line of the env file, replace the
   registration now with one that passes the maintenance token alone:

   ```bash
   claude mcp remove --scope local discord
   claude mcp add --scope local discord \
     -e DISCORD_MESSAGE_CONTENT=false \
     -e DISCORD_GUILD_MEMBERS=false \
     -e DISCORD_MCP_TOOLSETS=discovery,channels,permissions,roles \
     -- sh -c '. "$HOME/.config/<workbench>/.env"; DISCORD_TOKEN="$DISCORD_BOT_MAINTENANCE" DISCORD_ALLOWED_GUILDS="$DISCORD_ALLOWED_GUILDS" exec ~/.local/discord-mcp/node_modules/.bin/<binary>'
   ```

   The launch path is the local install from the server runbook's step 4, for
   the same reason it gives there. The `npx -y <package>@<version>` form is the
   quick variant and carries the same risk: it resolves and runs registry code
   at every launch, with a bot token in its environment.

8. **Give each bot its role.** Through the maintenance bot, add each lead bot
   to its lead role. Without the role, the post lock from the server runbook
   stops the bot in its own channel.

## Checks

Run each of these and read the output. Do not take any of them on trust.

- `GET /api/companies/{companyId}/secrets` lists one key per application,
  each starting with `discord-bot-`.
- The server's role list shows a member count of 1 on each lead role. If a
  role members call returns `Missing Access`, use the role list instead and
  record the failure as a finding rather than working around it.
- The server's member list shows every new bot and the maintenance bot.
- Each lead bot can post in the open channels.
- In any agent run, `GET /api/agents/me/secrets` lists no `discord-bot-` key.
  This is the check that proves the rule at the top of `README.md` holds.

Keep the Application IDs and the secret IDs. Neither is a secret, and
`discord-plugin-install.md` needs both.
