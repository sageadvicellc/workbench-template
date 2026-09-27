# Runbook: the agent bots

Builds one Discord application per lead, plus one system bot, and adds their
tokens to the env file the server runbook created. For the owner's own
interactive session, not for an agent. The layout from
`discord-server-setup.md` is already in place.

## What this builds

One application per lead agent, and one more for the system:

| Application | Posts for | Channel | Role |
|---|---|---|---|
| `<lead name>` | That lead, and the named subagents it runs | That lead's channel | That lead's role |
| `<system name>` | Any agent not in the rows above | System, approvals | none |

> FILL: replace the two rows above with one row per lead, and name the system
> bot.

A named subagent has no bot of its own. Work assigned to a subagent posts
through its lead's bot, in a thread in the lead's channel. Record that mapping
beside each application: one lead, one bot, and the agent IDs that post through
it.

The system bot is the default bot. It posts the system notices, and it is the
**only** bot that reads messages. It receives the owner's replies, button
clicks, and slash commands, and it joins the voice channel if live voice is on.
Every lead bot connects with message listening off, so none of them needs a
privileged intent.

## Before you start

- Create each application by hand in the developer portal. Discord has no
  public API that creates an application.
- Have the avatar images ready. Each goes on its application in step 2.
- Every token lives in the one env file from the server runbook, at mode 600
  and outside this repository. That file is the only place a token lives.
  Nothing in these runbooks copies a token into a second store.

## Steps

1. **Create the applications.** One per row of the table. Sign in with the
   account that owns the server.

2. **Set each bot.** On each application's Bot page:
   - Set the avatar.
   - Turn off Public Bot, so only you can invite it.
   - Decide the Message Content intent on the **system** application. Leave
     every privileged intent off on every lead application.

     Message Content is a privileged intent, and it is narrower than it looks.
     Without it, an app still receives message content in four cases.
     Discord's gateway documentation lists them under "Message Content
     Intent", at https://docs.discord.com/developers/events/gateway:

     - messages the app sends,
     - direct messages with the app,
     - messages that mention the app,
     - the message a message context menu command is used on.

     A thread reply that does not mention the bot is none of the four. So the
     bot does not see that text without the intent. A reply in a thread the
     bot started is still a reply that does not mention the bot.

     Button clicks and slash commands arrive as interactions, which carry
     their own payload, so they need no intent at all.

     If the owner wants to reply without mentioning the bot, turn the intent
     on. With it on, the bot reads the content of every message in every
     channel it can see.
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

   Write each value unquoted, and keep the file at mode 600. When a shell
   sources the file, it strips a quote. A reader that is not a shell keeps the
   quote. The quote then reaches Discord inside the token, and Discord answers
   with an authentication error, not a parse error.

   This file is now the only copy of every token. After any token reset, edit
   this file, then restart whatever reads it.

6. **Keep the Model Context Protocol server to its own token.** If the server
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

7. **Give each bot its role.** Through the maintenance bot, add each lead bot
   to its lead role. Without the role, the post lock from the server runbook
   stops the bot in its own channel.

## Checks

Run each of these and read the output. Do not take any of them on trust.

- The server's role list shows a member count of 1 on each lead role. If a
  role members call returns `Missing Access`, use the role list instead and
  record the failure as a finding rather than working around it.
- The server's member list shows every new bot and the maintenance bot.
- Each lead bot can post in the open channels.
- `ls -l ~/.config/<workbench>/.env` reports mode 600 and your own account.
  The env file is the only copy of every token, so this is the check that
  proves the rule at the top of `README.md` holds.

Keep each application's Application ID. An Application ID is not a secret, and
an ID is how anything that posts for an agent names the bot it posts through.
Record which lead each one belongs to, in the table under "What this builds".
