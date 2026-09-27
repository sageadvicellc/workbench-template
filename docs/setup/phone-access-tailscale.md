# Runbook: reach a local web service from a phone

Puts a web service that runs on this machine on the owner's own private
network. The owner then reads it and answers from a phone. For the owner's own
interactive session, not for an agent.

This is optional. Without it, the owner uses the service on the machine it runs
on, and the Discord layer carries everything else.

## What this is not

It is not a public address. Tailscale has a second feature, Funnel, that puts a
local server on the open internet. Do not use it for this. A local control
surface is the whole reach of whatever it controls, and the mode below
authorizes no one.

## The trade-off you are accepting

A local web service in a trusted loopback mode, often named `local_trusted`,
needs no key on loopback. Every request that reaches it is treated as the
owner. That is safe while the only thing that can reach it is the machine's own
loopback address.

Serving it on a private network widens "the only thing that can reach it" to
every device signed in to that network. So the safety now rests on two things
instead of one:

- The private network's own sign-in, which is the real gate.
- The hostname allowlist below, which is a check, not a gate.

Three more things are true, and each one is easy to miss:

- **The tailnet access control list is the gate that actually limits reach, and
  nothing below sets it.** Tailscale's default policy lets every node reach
  every other node. So every device on the tailnet can reach the service, not
  just the phone. Tighten that policy to the devices you mean, in the
  Tailscale admin console, and treat this runbook as incomplete until you
  have.
- **A tailnet can admit people you never invited.** A tailnet created with a
  Google Workspace or a Microsoft account can auto-join every user on that
  domain. "Just the owner's own devices" is sometimes false before you start.
  Read the tailnet's own user list before you accept the trade-off above.
- **There is no session on the phone.** In a trusted loopback mode the phone
  gets permanent, unauthenticated control of the service: no login, no logout,
  and no per-device record of who did what. A lost or unlocked phone is full
  control of the service, until you take the serve entry down.

When the network has just the owner's own devices on it, accept this. When the
network is shared, or when a device on it is shared, skip this runbook. Set an
API key and an `https` address instead. A key sent over plain `http` crosses
the network in the clear, so the two go together.

> FILL: say which you chose, and who else has a device on the network.

## Steps

1. **Install the private network client and sign in**, on the machine that
   runs the service and on the phone. Check that both appear in the same
   network.

2. **Find the machine's name on that network.** It is the short hostname, not
   the full address.

3. **Allow that hostname in the service.** A server that checks the `Host`
   header refuses a request whose hostname it does not know. Such a server must
   be told to accept the tailnet hostname. The command belongs to your own
   server, so read its own documentation for the real one:

   ```bash
   <your server's allowed-hostname command> <hostname>
   ```

   Run it once per hostname. Without it, the phone gets a rejected request and
   not a login page, which is easy to misread as the route being broken. When
   the server checks no `Host` header, skip this step, and expect nothing from
   the matching check below.

   Skipping it leaves one thing between a browser on any device on the private
   network and a service that asks for no sign-in: the network's own device
   list. Read that device list again before you skip this step.

4. **Serve the local port on the private network.** The service listens on
   loopback. Put that port on the network, in the background, so it survives
   the terminal closing:

   ```bash
   tailscale serve --bg <port>
   ```

   Read the port from the service's own configuration rather than assuming it.

   `--bg` persists across a reboot. The exposure outlives the session that
   created it, so it stays up until `tailscale serve reset` takes it down.

5. **Check what you published.** Read the list back before you open anything
   on the phone:

   ```bash
   tailscale serve status
   ```

   Check that there is one entry, for the port you meant, and no Funnel entry.
   To take it down:

   ```bash
   tailscale serve reset
   ```

6. **Open it on the phone.** The address is the machine's name on the private
   network. In a trusted loopback mode the service asks for no sign-in, so it
   opens straight away: that is the trade-off above, not a fault. In an
   authenticated mode, sign in.

## Checks

- `tailscale serve status` lists exactly one entry, and it is not a Funnel.
- A device that is not signed in to the private network cannot reach the
  address at all.
- The phone can open the service and use it.
- A request with a hostname you did not allow is refused. This proves step 3
  is doing something.

## When the machine changes

A new machine gets a new hostname, so step 3 runs again there. `tailscale
serve` state belongs to the machine and does not travel. Neither does the
service's own data. Read that service's documentation on where its data
directory and its keys live before you move anything. Expect to recreate every
secret rather than copy it.
