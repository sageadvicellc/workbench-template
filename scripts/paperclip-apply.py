#!/usr/bin/env python3
"""Make the live Paperclip company match `paperclip/company.json`.

The tracked files under `paperclip/` are the source of truth for the v2 team:
the company flags, the instance switches that create work on their own, the
`scope-creep` label, and each agent's adapter, heartbeat, permissions, wake
prompt, and `AGENTS.md`. This script reads the live state, prints every
difference, and changes nothing unless `--apply` is given.

    python3 scripts/paperclip-apply.py            # dry run: print the plan
    python3 scripts/paperclip-apply.py --apply    # send it

An agent in the config with no `id` is matched by name. If no live agent has
that name, `--apply` creates it and prints its new id; copy the id into
`company.json` afterwards.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperclip_lib import (  # noqa: E402
    DEFAULT_CONFIG,
    REPO_ROOT,
    Action,
    Client,
    PaperclipError,
    agent_ids,
    load_config,
)


def _diff(desired, current):
    return {k: v for k, v in desired.items() if current.get(k) != v}


def _adapter_type(agent):
    return agent.get("adapterType", "claude_local")


def _desired_adapter(cfg, agent, root):
    """Common settings, then the adapter's own profile, then the agent's."""
    d = cfg["defaults"]
    wake = (Path(root) / d["wakePromptFile"]).read_text()
    profile = d.get("adapters", {}).get(_adapter_type(agent), {})
    return {**d["adapterConfig"], **profile, **agent.get("adapterConfig", {}), "promptTemplate": wake}


def _instructions(agent, root):
    return (Path(root) / agent["instructionsFile"]).read_text()


def _plan_company(cfg, client):
    cid = cfg["companyId"]
    actions = []
    diff = _diff(cfg.get("company", {}), client.get(f"/api/companies/{cid}"))
    if diff:
        actions.append(Action("PATCH", f"/api/companies/{cid}", diff, f"company: set {sorted(diff)}"))
    if cfg.get("experimental"):
        diff = _diff(cfg["experimental"], client.get("/api/instance/settings/experimental"))
        if diff:
            actions.append(Action("PATCH", "/api/instance/settings/experimental", diff,
                                  f"instance: set {sorted(diff)}"))
    have = {label["name"] for label in client.get(f"/api/companies/{cid}/labels")}
    for label in cfg.get("labels", []):
        if label["name"] not in have:
            actions.append(Action("POST", f"/api/companies/{cid}/labels", dict(label),
                                  f"label: create {label['name']}"))
    return actions


def _plan_new_agent(cfg, agent, root):
    d = cfg["defaults"]
    body = {
        "name": agent["name"],
        "role": agent["role"],
        "title": agent.get("title"),
        "adapterType": _adapter_type(agent),
        # The server refuses promptTemplate on a new agent. The second pass in
        # main() sets it with a PATCH once the agent exists.
        "adapterConfig": {k: v for k, v in _desired_adapter(cfg, agent, root).items() if k != "promptTemplate"},
        "runtimeConfig": d["runtimeConfig"],
        "permissions": d["permissions"],
        "instructionsBundle": {"entryFile": "AGENTS.md",
                               "files": {"AGENTS.md": _instructions(agent, root)}},
    }
    # With board approval required, even the board hires through /agent-hires.
    # run_actions approves the hire it creates, because running this script
    # with --apply is the board's approval.
    return Action("POST", f"/api/companies/{cfg['companyId']}/agent-hires", body,
                  f"agent {agent['name']}: hire")


def _plan_existing_agent(cfg, agent, live, client, root):
    d = cfg["defaults"]
    aid = live["id"]
    actions = []

    patch = _diff({"name": agent["name"], "role": agent["role"], "title": agent.get("title"),
                   "adapterType": _adapter_type(agent)}, live)
    current = live.get("adapterConfig") or {}
    desired = _desired_adapter(cfg, agent, root)
    if "adapterType" in patch:
        # A new runtime takes a clean config. Keep only the managed instructions
        # fields, which Paperclip owns and the next runtime still reads.
        kept = {k: v for k, v in current.items() if k.startswith("instructions")}
        adapter = {**kept, **desired}
        patch["adapterConfig"] = adapter
        patch["replaceAdapterConfig"] = True
    else:
        adapter = _diff(desired, current)
        if adapter:
            patch["adapterConfig"] = adapter
    runtime = live.get("runtimeConfig") or {}
    heartbeat = {**runtime.get("heartbeat", {}), **d["runtimeConfig"]["heartbeat"]}
    if heartbeat != runtime.get("heartbeat"):
        patch["runtimeConfig"] = {**runtime, "heartbeat": heartbeat}
        # The server stores a model profile without `adapterConfig` but rejects
        # one sent back that way, so an echoed profile gets an empty one.
        profiles = runtime.get("modelProfiles")
        if isinstance(profiles, dict):
            patch["runtimeConfig"]["modelProfiles"] = {
                name: ({"adapterConfig": {}, **prof} if isinstance(prof, dict) else prof)
                for name, prof in profiles.items()
            }
    if patch:
        changed = sorted(set(patch) - {"adapterConfig", "replaceAdapterConfig"} | {f"adapterConfig.{k}" for k in adapter})
        actions.append(Action("PATCH", f"/api/agents/{aid}", patch, f"agent {agent['name']}: set {changed}"))

    if _diff(d["permissions"], live.get("permissions") or {}):
        actions.append(Action("PATCH", f"/api/agents/{aid}/permissions", dict(d["permissions"]),
                              f"agent {agent['name']}: permissions"))

    wanted = _instructions(agent, root)
    current = client.get(f"/api/agents/{aid}/instructions-bundle/file?path=AGENTS.md") or {}
    if current.get("content") != wanted:
        actions.append(Action("PUT", f"/api/agents/{aid}/instructions-bundle/file",
                              {"path": "AGENTS.md", "content": wanted},
                              f"agent {agent['name']}: replace AGENTS.md"))
    return actions


def plan_actions(cfg, client, root=REPO_ROOT):
    actions = _plan_company(cfg, client)
    live_agents = client.get(f"/api/companies/{cfg['companyId']}/agents")
    ids = agent_ids(cfg, live_agents)
    by_id = {a["id"]: a for a in live_agents}
    for agent in cfg["agents"]:
        aid = ids.get(agent["key"])
        if aid is None:
            actions.append(_plan_new_agent(cfg, agent, root))
        else:
            actions.extend(_plan_existing_agent(cfg, agent, by_id[aid], client, root))
    return actions


def run_actions(actions, client, apply, echo=None):
    """Send or describe each action in order. Each line is echoed as it happens,
    so a failure part way through still leaves a record of what landed."""
    lines = []
    for n, action in enumerate(actions, 1):
        if apply:
            try:
                result = client.send(action.method, action.path, action.body)
            except PaperclipError as err:
                raise PaperclipError(f"{n - 1} of {len(actions)} change(s) applied before this failure: {err}") from err
            note = ""
            if action.path.endswith("/agent-hires") and result:
                agent = result.get("agent") or {}
                approval = result.get("approval") or {}
                if approval.get("id"):
                    try:
                        client.send("POST", f"/api/approvals/{approval['id']}/approve",
                                    {"decisionNote": "Approved by paperclip-apply.py --apply"})
                    except PaperclipError as err:
                        raise PaperclipError(
                            f"{n} of {len(actions)} change(s) applied. The hire of {action.body.get('name')} "
                            f"landed as agent {agent.get('id')}, but its approval {approval['id']} failed, "
                            f"so approve it in the Paperclip UI: {err}") from err
                note = f" (new id {agent.get('id')}; copy it into company.json)"
            line = f"done: {action.summary}{note}"
        else:
            line = f"plan: {action.method} {action.path} :: {action.summary}"
        lines.append(line)
        if echo:
            echo(line)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--apply", action="store_true", help="send the changes; default is a dry run")
    parser.add_argument("--show-bodies", action="store_true", help="print each request body")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    client = Client(cfg["apiBase"])
    try:
        actions = plan_actions(cfg, client)
        if args.show_bodies:
            for a in actions:
                print(f"{a.method} {a.path}\n{json.dumps(a.body, indent=2)}\n")
        run_actions(actions, client, args.apply, echo=print)
        if args.apply and actions:
            # A hire gets a default task-assign grant after creation, so a
            # second pass puts the permissions back to what the config says.
            again = plan_actions(cfg, client)
            if again:
                print(f"second pass: {len(again)} change(s) the first pass set off")
                run_actions(again, client, True, echo=print)
    except PaperclipError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    if not actions:
        print("in sync: nothing to change")
    elif not args.apply:
        print(f"{len(actions)} change(s) planned. Run again with --apply to send them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
