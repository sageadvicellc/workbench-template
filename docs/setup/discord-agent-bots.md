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
   - Turn on the Message Content intent on the **system** application only.
     Leave every privileged intent off on every lead application.
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
   import json, os, pathlib, urllib.request

   company = os.environ["PAPERCLIP_COMPANY_ID"]
   base = os.environ.get("PAPERCLIP_API_URL", "http://127.0.0.1:3100").rstrip("/")
   if not base.endswith("/api"):
       base += "/api"
   env_path = pathlib.Path.home() / ".config" / os.environ["WORKBENCH_NAME"] / ".env"
   names = os.environ["DISCORD_BOT_NAMES"].split()

   env = {}
   for line in env_path.read_text().splitlines():
       if "=" in line and not line.lstrip().startswith("#"):
           key, value = line.split("=", 1)
           env[key.strip()] = value.strip()

   def call(method, path, body=None):
       request = urllib.request.Request(
           base + path,
           method=method,
           data=json.dumps(body).encode() if body is not None else None,
           headers={"Content-Type": "application/json"},
       )
       with urllib.request.urlopen(request) as response:
           return json.load(response)

   existing = {s["key"]: s["id"] for s in call("GET", f"/companies/{company}/secrets")}
   for name in names:
       value = env.get(f"DISCORD_BOT_{name.upper()}")
       if not value:
           print(name, "missing from the env file")
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
   PY
   ```

   Set `PAPERCLIP_COMPANY_ID`, `WORKBENCH_NAME`, and `DISCORD_BOT_NAMES`
   before you run it. `DISCORD_BOT_NAMES` is a space-separated list, one name
   per application, matching the suffixes you used in step 5.

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
     -- sh -c '. "$HOME/.config/<workbench>/.env"; DISCORD_TOKEN="$DISCORD_BOT_MAINTENANCE" DISCORD_ALLOWED_GUILDS="$DISCORD_ALLOWED_GUILDS" exec npx -y <package>@<version>'
   ```

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
