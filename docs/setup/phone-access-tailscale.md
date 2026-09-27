# Runbook: reach Paperclip from a phone

Puts the Paperclip web interface on the owner's own private network, so the
owner can approve a scope and read a delivery from a phone. For the owner's own
interactive session, not for a Paperclip agent.

This is optional. Without it, the owner approves from the machine Paperclip
runs on, and the Discord layer carries everything else.

## What this is not

It is not a public address. Tailscale has a second feature, Funnel, that puts a
local server on the open internet. Do not use it for this. Paperclip's board
routes are the company's whole control surface, and the mode below authorises
no one.

## The trade-off you are accepting

Paperclip in `local_trusted` mode needs no key on loopback. Every request that
reaches it is treated as the board. That is safe while the only thing that can
reach it is the machine's own loopback address.

Serving it on a private network widens "the only thing that can reach it" to
every device signed in to that network. So the safety now rests on two things
instead of one:

- The private network's own sign-in, which is the real gate.
- The hostname allowlist below, which is a check, not a gate.

Accept this only if the network has just the owner's own devices on it. If it
is shared, or if a device on it is shared, set a board API key and an `https`
address instead, and skip this runbook. The Paperclip client refuses to send a
key over plain `http` to any host but loopback, so the two go together.

> FILL: say which you chose, and who else has a device on the network.

## Steps

1. **Install the private network client and sign in**, on the machine that
   runs Paperclip and on the phone. Confirm both appear in the same network.

2. **Find the machine's name on that network.** It is the short hostname, not
   the full address.

3. **Allow that hostname in Paperclip.** Paperclip refuses a request whose
   `Host` header it does not recognise, in authenticated and private modes:

   ```bash
   paperclipai allowed-hostname <hostname>
   ```

   Run it once per hostname. Without it, the phone gets a rejected request and
   not a login page, which is easy to misread as the route being broken.

4. **Serve the local port on the private network.** Paperclip listens on
   loopback. Put that port on the network, in the background, so it survives
   the terminal closing:

   ```bash
   tailscale serve --bg <port>
   ```

   The default port is `3100`. Read the real one from the Paperclip config
   rather than assuming it.

5. **Check what you published.** Read the list back before you open anything
   on the phone:

   ```bash
   tailscale serve status
   ```

   Confirm one entry, for the port you meant, and no Funnel entry. To take it
   down:

   ```bash
   tailscale serve reset
   ```

6. **Open it on the phone.** The address is the machine's name on the private
   network. Sign in to Paperclip if the mode asks you to.

## Checks

- `tailscale serve status` lists exactly one entry, and it is not a Funnel.
- A device that is not signed in to the private network cannot reach the
  address at all.
- The phone can open the issue list, approve a scope, and comment.
- A request with a hostname you did not allow is refused. This proves step 3
  is doing something.

## When the machine changes

A new machine gets a new hostname, so step 3 runs again there. `tailscale
serve` state belongs to the machine and does not travel. Neither does
Paperclip's data: read the Paperclip documentation on where its instance
directory and its secret key live before you move anything, and expect to
recreate every secret rather than copy it.
