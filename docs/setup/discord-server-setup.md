# Runbook: the Discord server

Builds the server, its channels, its roles, and one maintenance bot. For the
owner's own interactive session, not for a Paperclip agent. Read
`docs/setup/README.md` first.

The pattern this follows: a setup bot, driven from a local Model Context
Protocol server, configures the server. A Model Context Protocol server is a
small program a harness launches and calls tools on. The bot then stays as the
server's maintenance bot, for every later change to channels and roles.

## Why this shape

One rule decides it: no bot token reaches an agent's runtime. This variant
keeps the rule by never handing the Model Context Protocol server or its token
to any Paperclip agent. Only the owner's own sessions hold that token.

The agent bots are separate Discord applications with their own tokens, built
in `discord-agent-bots.md`. This runbook creates none of them. It builds only
the channel and role layout they post into.

## Before you start

- Create the server by hand, in the Discord client. No documented Discord API
  creates a guild. Do not use an endpoint you found in an issue thread.
- Choose the Model Context Protocol server before you start, and read its
  README for its exact tool names. A package that takes the token as a command
  line flag writes the token into shell history. Prefer one that reads the
  token from the environment.
  > FILL: name the package and the version you pinned, and say where you read
  > its tool list.
- Never trust a tool name from memory. Step 5 checks the live list.

## Steps

1. **Create the server.** In the Discord client, create a server owned by the
   owner's own account. Name it and leave it private.

2. **Create the maintenance bot application.** In the Discord developer
   portal, create one application, add a bot user to it, and copy its token.
   Do not turn on the Message Content intent. No tool in this runbook reads
   message content.

3. **Set its permissions.** Do not grant `ADMINISTRATOR`. Grant only what the
   layout needs:
   - `MANAGE_CHANNELS`, `MANAGE_ROLES`, `MANAGE_THREADS`
   - `CREATE_PUBLIC_THREADS`, `CREATE_PRIVATE_THREADS`
   - `SEND_MESSAGES`, `SEND_MESSAGES_IN_THREADS`, `EMBED_LINKS`,
     `ADD_REACTIONS`
   - `VIEW_CHANNEL`, `READ_MESSAGE_HISTORY`

   Two permissions are absent on purpose, so that a later reader does not add
   them back:

   - `MANAGE_WEBHOOKS` is absent because no step in any runbook here creates a
     webhook with this bot, and the permission lets its holder list a channel's
     webhooks. That listing returns the webhook token, which is the URL
     `discord-plugin-install.md` says is never written anywhere.
   - `VIEW_AUDIT_LOG` is absent because the pinned tool sets in step 4 do not
     use it.

   Build the invite URL with the `bot` scope and these permission bits. Open
   it and add the bot to the server.

4. **Keep the token in an env file outside this tree.** Put the file at
   `~/.config/<workbench>/.env`, so that no agent workspace under this tree
   contains it. It starts with two lines. The agent bot tokens join it in the
   next runbook.

   ```bash
   DISCORD_BOT_MAINTENANCE=<the token from step 2>
   DISCORD_ALLOWED_GUILDS=<the server ID from step 1>
   ```

   Restrict the file to your own account:

   ```bash
   chmod 600 ~/.config/<workbench>/.env
   ```

   Register the Model Context Protocol server at local scope, so that the
   registration covers this directory only and git does not track it. The
   command reads the token at launch, so no token enters a config file. Pass
   only the two lines the server needs, never the whole file. Turn off both
   privileged intents and limit the tool set, or the gateway refuses the login
   with `Used disallowed intents`:

   Install the server package to a path of your own first, and launch that
   path. `npx -y <package>@<version>` resolves and runs registry code at every
   launch, with a token holding `MANAGE_ROLES` and `MANAGE_CHANNELS` in its
   environment. The version pin narrows that; it is not an integrity check, and
   there is no lockfile:

   ```bash
   mkdir -p ~/.local/discord-mcp && cd ~/.local/discord-mcp
   npm init -y
   npm install --save-exact <package>@<version>
   ```

   `npm install` writes `package-lock.json` beside it, with an `integrity` hash
   per package. Keep that file. A later `npm ci` in the same directory
   reinstalls exactly those bytes and fails if the registry serves anything
   else. Read the installed package's `bin` entry for the launch path below.

   ```bash
   claude mcp add --scope local discord \
     -e DISCORD_MESSAGE_CONTENT=false \
     -e DISCORD_GUILD_MEMBERS=false \
     -e DISCORD_MCP_TOOLSETS=discovery,channels,permissions,roles \
     -- sh -c '. "$HOME/.config/<workbench>/.env"; DISCORD_TOKEN="$DISCORD_BOT_MAINTENANCE" DISCORD_ALLOWED_GUILDS="$DISCORD_ALLOWED_GUILDS" exec "$HOME/.local/discord-mcp/node_modules/.bin/<binary>"'
   ```

   The quick variant is `exec npx -y <package>@<version>` in place of that
   path. It needs no install step and it takes the risk named above at every
   launch.

   **The env file must not use `export`.** Sourcing it with `.` leaves every
   line an unexported shell variable, so only the `DISCORD_TOKEN` and
   `DISCORD_ALLOWED_GUILDS` assignments prefixed on the `exec` line reach the
   child process. That is the whole reason the other tokens stay out of the
   server's environment. Write one `export` in that file and every token in it
   reaches this process, silently.

   Never write the token to a tracked file or to a Paperclip secret. Do not
   pass a second `discord` server on the command line. A second entry of the
   same name overrides this one.

5. **Check the tool list before you change anything.** Call the server's
   `tools/list` and read the result. Make sure it matches the README: channel
   creation, thread creation, permission overwrites, role management. Do this
   before any tool that changes server state. A tool that is not on the list
   is a finding. Stop and say so. Do not guess a name.

6. **Build the layout.** In one category, with the checked tools:
   - One text channel per lead agent, named for that lead.
   - One text channel for approvals and one for system notices.
   - One voice channel, if live voice is wanted.
   - One role per lead, with no members yet. Name each role for the job, not
     for the agent, so that replacing the agent does not rename the role.
   - A post lock on each lead channel. `@everyone` may read it but may not
     send messages, send in threads, or create threads. The matching role may
     do all three.

   > FILL: list the channels and roles you built, and say which lead maps to
   > which channel.

7. **Keep the bot for maintenance.** The application stays. It applies every
   later change to channels and roles, from the owner's own sessions only. If
   the token leaks, reset it in the developer portal and replace the line in
   the env file.

## After this runs

- The only copy of the token outside Discord is the step 4 env file.
- The server has its channel and role layout, and no bot in any role yet.
- The agent bots and their tokens are the next runbook.
- If the layout differs from what you planned, append the difference to
  `DECISIONS.md` with the reason.
