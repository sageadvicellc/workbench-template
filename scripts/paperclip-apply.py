#!/usr/bin/env python3
"""Make the live Paperclip company match `paperclip/company.json`.

The tracked files under `paperclip/` are the source of truth for the team: the
company flags, the instance switches that create work on their own, the labels,
the org chart, the run-cap breaker, each agent's adapter, heartbeat,
permissions, wake prompt, and `AGENTS.md`, and each routine. This script reads
the live state, prints every difference, and changes nothing unless `--apply`
is given. It compares before it writes, so it is safe to run again after a
failure: the rerun plans only what is still different.

    python3 scripts/paperclip-apply.py            # dry run: print the plan
    python3 scripts/paperclip-apply.py --apply    # send it

`--config paperclip/orgs/<name>.json` runs the same team against another
company, with that overlay's goals and caps. `scripts/paperclip-new-org.py`
creates the company first.

An agent in the config with no `id` is matched by name. If no live agent has
that name, `--apply` creates it and prints its new id; copy the id into
`company.json` afterwards. An agent whose config carries `"status": "paused"`,
such as a standby twin under an overlay's `extraAgents`, is hired the same way
and then paused, since the hire API takes no starting status.

Two settings stay off by default: `company["applyAssignmentPolicy"]`
(protected agents and `tasks:assign_scope` grants) and
`company["applyPipelines"]` (pipelines). Each needs a proof run against a
throwaway test company first. Flip the matching flag in `company.json` once
that proof lands.
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


def _desired_heartbeat(cfg, agent):
    """The company's heartbeat, then the agent's own `maxConcurrentRuns`.

    The heartbeat stays off. A heartbeat timer wakes an idle agent on a clock,
    which is an unbounded loop with nothing asking for the work, so
    `defaults.runtimeConfig.heartbeat.enabled` is `false` and this function
    never turns it on.

    One agent runs `maxConcurrentRuns` issues at once, each in its own session,
    so a worker role is one agent with several slots rather than numbered
    clones.
    """
    heartbeat = dict(cfg["defaults"]["runtimeConfig"]["heartbeat"])
    if "maxConcurrentRuns" in agent:
        heartbeat["maxConcurrentRuns"] = agent["maxConcurrentRuns"]
    return heartbeat


def _desired_permissions(cfg, agent):
    """The company's default permissions, then the agent's own `permissions`.

    A lead sets `canAssignTasks: true` here; every other agent keeps the
    default.
    """
    return {**cfg["defaults"]["permissions"], **agent.get("permissions", {})}


def _instructions(agent, root):
    """The agent's `AGENTS.md` text. A missing file is a config error that names
    the agent and the path, so even a dry run says what is absent."""
    path = Path(root) / agent["instructionsFile"]
    try:
        return path.read_text()
    except FileNotFoundError as err:
        raise PaperclipError(
            f"agent {agent['key']!r}: instructions file {agent['instructionsFile']} does not exist "
            f"under {root}; add it or fix instructionsFile in company.json") from err


def _resolve_agent_ref(ids, key):
    """A configured agent key to its live id. `None` passes through unchanged.

    A key that names no live agent is a config error, not an absent value, so
    it raises rather than silently sending a `null` reference in its place.
    """
    if key is None:
        return None
    if key not in ids:
        raise PaperclipError(f"agent key {key!r} has no live match; check company.json")
    return ids[key]


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


def _configured_agent_keys(cfg):
    return {a["key"] for a in cfg.get("agents", [])}


def _resolve_reports_to_for_hire(cfg, ids, key):
    """`reportsTo` on a brand-new agent's hire body.

    A fresh company hires several agents in one pass, in no guaranteed order,
    so a report's manager can easily still be unhired when this body is built.
    A key naming another *configured* agent is not yet a config error in that
    case, only "not live yet": hire without `reportsTo` and let the existing
    second pass in main() (which reruns `plan_actions` once every hire from the
    first pass has landed) PATCH it in once the manager has a live id. A key
    naming no configured agent at all is still a config error.
    """
    if key is None or key in ids:
        return _resolve_agent_ref(ids, key)
    if key in _configured_agent_keys(cfg):
        return None
    raise PaperclipError(f"agent key {key!r} has no live match; check company.json")


def _plan_new_agent(cfg, agent, root, ids):
    d = cfg["defaults"]
    body = {
        "name": agent["name"],
        "role": agent["role"],
        "title": agent.get("title"),
        "adapterType": _adapter_type(agent),
        "reportsTo": _resolve_reports_to_for_hire(cfg, ids, agent.get("reportsTo")),
        # The server refuses promptTemplate on a new agent. The second pass in
        # main() sets it with a PATCH once the agent exists.
        "adapterConfig": {k: v for k, v in _desired_adapter(cfg, agent, root).items() if k != "promptTemplate"},
        "runtimeConfig": {**d["runtimeConfig"], "heartbeat": _desired_heartbeat(cfg, agent)},
        "permissions": _desired_permissions(cfg, agent),
        "instructionsBundle": {"entryFile": "AGENTS.md",
                               "files": {"AGENTS.md": _instructions(agent, root)}},
    }
    # With board approval required, even the board hires through /agent-hires.
    # run_actions approves the hire it creates, because running this script with
    # --apply is the board's approval.
    return Action("POST", f"/api/companies/{cfg['companyId']}/agent-hires", body,
                  f"agent {agent['name']}: hire")


def _plan_agent_status(agent, live):
    """A config agent's own desired `status`. Only `"paused"` is understood
    today: a standby twin is hired active, like any agent, because the hire API
    takes no starting status, so this pauses it right after, the same
    `POST /api/agents/{id}/pause` call a cap pause sends. A live agent already
    in that status is left alone, the same way every other pause action in this
    file checks live status first rather than sending a redundant call."""
    if agent.get("status") != "paused" or live.get("status") == "paused":
        return []
    return [Action("POST", f"/api/agents/{live['id']}/pause", None,
                   f"agent {agent['name']}: pause (created paused)")]


def _plan_existing_agent(cfg, agent, live, client, root, ids):
    aid = live["id"]
    actions = list(_plan_agent_status(agent, live))

    patch = _diff({"name": agent["name"], "role": agent["role"], "title": agent.get("title"),
                   "adapterType": _adapter_type(agent),
                   "reportsTo": _resolve_agent_ref(ids, agent.get("reportsTo"))}, live)
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
    heartbeat = {**runtime.get("heartbeat", {}), **_desired_heartbeat(cfg, agent)}
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
        changed = sorted(set(patch) - {"adapterConfig", "replaceAdapterConfig"}
                         | {f"adapterConfig.{k}" for k in adapter})
        actions.append(Action("PATCH", f"/api/agents/{aid}", patch, f"agent {agent['name']}: set {changed}"))

    permissions = _desired_permissions(cfg, agent)
    if _diff(permissions, live.get("permissions") or {}):
        actions.append(Action("PATCH", f"/api/agents/{aid}/permissions", permissions,
                              f"agent {agent['name']}: permissions"))

    wanted = _instructions(agent, root)
    current = client.get(f"/api/agents/{aid}/instructions-bundle/file?path=AGENTS.md") or {}
    if current.get("content") != wanted:
        actions.append(Action("PUT", f"/api/agents/{aid}/instructions-bundle/file",
                              {"path": "AGENTS.md", "content": wanted},
                              f"agent {agent['name']}: replace AGENTS.md"))
    return actions


def _resolve_grant_scope(ids, grant):
    """The config's `assignScopeGrant`, with each agent key turned into its live id."""
    if not grant:
        return None
    scope = {}
    if "subtreeRootAgentId" in grant:
        scope["subtreeRootAgentId"] = _resolve_agent_ref(ids, grant["subtreeRootAgentId"])
    if "agentIds" in grant:
        scope["agentIds"] = [_resolve_agent_ref(ids, k) for k in grant["agentIds"]]
    return scope


def _plan_assignment_policy(cfg, agent, live, ids):
    """Protected mode and the `tasks:assign_scope` grant for one agent.

    Off until `company["applyAssignmentPolicy"]` is true, because the exit
    tests must pass against a throwaway company first.
    """
    if not cfg.get("applyAssignmentPolicy"):
        return []
    aid = live["id"]
    actions = []
    if agent.get("protected"):
        policy = (live.get("permissions") or {}).get("authorizationPolicy") or {}
        if (policy.get("assignmentPolicy") or {}).get("mode") != "protected":
            # canCreateAgents and canAssignTasks are required on this route.
            # Sent as the config's own values for this agent, not live's current
            # values, so this action agrees with `_plan_existing_agent`'s
            # permissions patch rather than racing it back to a stale value.
            d = _desired_permissions(cfg, agent)
            actions.append(Action(
                "PATCH", f"/api/agents/{aid}/permissions",
                {"canCreateAgents": d.get("canCreateAgents", False),
                 "canAssignTasks": d.get("canAssignTasks", False),
                 "authorizationPolicy": {"assignmentPolicy": {"mode": "protected"}}},
                f"agent {agent['name']}: set protected mode"))
    scope = _resolve_grant_scope(ids, agent.get("assignScopeGrant"))
    if scope is not None:
        membership = (live.get("access") or {}).get("membership") or {}
        grants = (live.get("access") or {}).get("grants") or []
        current_scope = next((g.get("scope") for g in grants
                              if g.get("permissionKey") == "tasks:assign_scope"), None)
        if membership.get("id") and current_scope != scope:
            # This route replaces the member's whole grant list, so every other
            # grant the member holds is carried over unchanged, and `status` is
            # echoed back rather than forced to "active", so granting the scope
            # never reactivates a suspended membership.
            other_grants = [g for g in grants if g.get("permissionKey") != "tasks:assign_scope"]
            desired_grants = other_grants + [{"permissionKey": "tasks:assign_scope", "scope": scope}]
            actions.append(Action(
                "PATCH", f"/api/companies/{cfg['companyId']}/members/{membership['id']}/role-and-grants",
                {"status": membership.get("status") or "active", "grants": desired_grants},
                f"agent {agent['name']}: set tasks:assign_scope grant"))
    return actions


def _resolve_stage_config(config, ids):
    """A stage's `automation.assigneeAgent` config key to the
    `automation.assigneeAgentId` field the API reads."""
    automation = config.get("automation")
    if not automation or "assigneeAgent" not in automation:
        return config
    resolved = dict(automation)
    key = resolved.pop("assigneeAgent")
    resolved["assigneeAgentId"] = _resolve_agent_ref(ids, key)
    return {**config, "automation": resolved}


def _validate_stage_approver(stage):
    """Fail loudly on the old `{"type": "user", "userId": ...}` approver shape.

    The server reads only `{"kind": ..., "id": ...}` and silently treats
    anything else as `{"kind": "any_human"}`. Sending that shape would quietly
    turn a named approver into "any human can pass this stage," so this check
    runs before any pipeline write.
    """
    approver = (stage.get("config") or {}).get("approver")
    if approver is None:
        return
    if not isinstance(approver, dict) or "kind" not in approver:
        raise PaperclipError(
            f"stage {stage.get('key')!r}: approver must be {{'kind': ..., 'id': ...}}; got {approver!r}. "
            "The old {'type': 'user', 'userId': ...} shape is silently read by the server as any_human."
        )
    kind = approver["kind"]
    if kind not in ("any_human", "user", "agent"):
        raise PaperclipError(
            f"stage {stage.get('key')!r}: approver kind must be any_human, user, or agent; got {kind!r}")
    if kind in ("user", "agent") and not approver.get("id"):
        raise PaperclipError(f"stage {stage.get('key')!r}: approver kind {kind!r} requires a non-empty 'id'")


def _drift_note(name, problems):
    return Action("NOTE", "__drift__", None,
                  f"pipeline {name}: {'; '.join(problems)}; fix by hand or archive it")


def _stage_is_wired(live_config):
    """Whether a live stage's config shows its routine already attached.

    A wired stage's config carries `{"onEnter": {"type": "run_routine",
    "routineId": "<uuid>", ...}, ...}`.
    """
    on_enter = live_config.get("onEnter") or {}
    return on_enter.get("type") == "run_routine" and bool(on_enter.get("routineId"))


def _wired_routine_id(live_config):
    return (live_config.get("onEnter") or {}).get("routineId")


def _routines_by_id(cfg, client):
    cid = cfg["companyId"]
    return {r["id"]: r for r in (client.get(f"/api/companies/{cid}/routines") or []) if r.get("id")}


_COMPARABLE_STAGE_FIELDS = ("approver", "requireApproval", "approveToStageKey", "rejectToStageKey")


def _stage_config_mismatches(key, desired_config, live_config):
    """Field-by-field drift between a stage's file config and its live one.

    Compares only a field the file actually sets, so a field the server adds or
    omits on its own never becomes false drift. Each mismatch names the stage
    and field, and the desired value against the live one.
    """
    mismatches = []
    for field in _COMPARABLE_STAGE_FIELDS:
        if field not in desired_config:
            continue
        desired_value = desired_config[field]
        live_value = live_config.get(field)
        if desired_value != live_value:
            mismatches.append(f"stage {key} {field}: desired {desired_value!r} != live {live_value!r}")
    return mismatches


def _plan_existing_pipeline_drift(name, live, client):
    """A pipeline that exists by name may still be half-built, or built wrong:
    created but never given its later stages, an approver the server silently
    downgraded, or automation wired to the wrong agent. Report that as drift
    rather than silently calling it in sync. Nothing here writes anything.
    """
    pid = live.get("id")
    detail = client.get(f"/api/pipelines/{pid}") if pid else live
    return {s["key"]: s for s in (detail.get("stages") or [])}


def _plan_pipelines(cfg, client, root, ids):
    """Create each configured pipeline, with every stage, if none exists by
    name; report drift, never silence, on one that exists but does not match.

    Every stage goes in the one pipeline-create call. Creating stages one at a
    time gets a 422 the moment an earlier `review` stage's
    `approveToStageKey`/`rejectToStageKey` names a stage that does not exist
    yet. `config.automation` is stripped from every stage in that call
    regardless, because the server strips it there too; a PATCH to each
    automated stage's own id, read back from the create response's `stages`
    array (matched by `key`), sets it afterward. That PATCH carries the stage's
    full stripped config plus `automation`, not automation alone, because
    whether the server merges or replaces `config` is unverified.

    Off until `company["applyPipelines"]` is true, because the exit test must
    pass against a throwaway company first.
    """
    if not cfg.get("applyPipelines"):
        return []
    cid = cfg["companyId"]
    live_pipelines = {p["name"]: p for p in (client.get(f"/api/companies/{cid}/pipelines") or [])}
    actions = []
    for entry in cfg.get("pipelines", []):
        spec = json.loads((Path(root) / entry["file"]).read_text())
        name = spec["name"]
        for stage in spec["stages"]:
            _validate_stage_approver(stage)

        if name in live_pipelines:
            live_stages = _plan_existing_pipeline_drift(name, live_pipelines[name], client)
            problems = []
            missing = [s["key"] for s in spec["stages"] if s["key"] not in live_stages]
            if missing:
                problems.append(f"missing stages {missing}")
            routines_by_id = None
            for stage in spec["stages"]:
                key = stage["key"]
                if key not in live_stages:
                    continue
                desired_config = _resolve_stage_config(stage.get("config") or {}, ids)
                live_config = live_stages[key].get("config") or {}
                automation = desired_config.get("automation")
                desired_fields = {k: v for k, v in desired_config.items() if k != "automation"}
                problems.extend(_stage_config_mismatches(key, desired_fields, live_config))
                if automation:
                    if not _stage_is_wired(live_config):
                        problems.append(f"stage {key}: no automation wired")
                    else:
                        if routines_by_id is None:
                            routines_by_id = _routines_by_id(cfg, client)
                        routine = routines_by_id.get(_wired_routine_id(live_config)) or {}
                        desired_assignee = automation.get("assigneeAgentId")
                        live_assignee = routine.get("assigneeAgentId")
                        if desired_assignee != live_assignee:
                            problems.append(f"stage {key} automation assignee: "
                                            f"desired {desired_assignee!r} != live {live_assignee!r}")
            if problems:
                actions.append(_drift_note(name, problems))
            continue

        ref = f"pipeline:{name}"
        stripped_stages = []
        stage_patches = {}
        for stage in spec["stages"]:
            resolved_config = _resolve_stage_config(stage.get("config", {}), ids)
            automation = resolved_config.get("automation")
            stripped_config = {k: v for k, v in resolved_config.items() if k != "automation"}
            stripped_stages.append({**stage, "config": stripped_config})
            if automation:
                stage_patches[stage["key"]] = {**stripped_config, "automation": automation}
        actions.append(Action("POST", f"/api/companies/{cid}/pipelines",
                              {"key": entry["key"], "name": name, "stages": stripped_stages},
                              f"pipeline {name}: create with {len(stripped_stages)} stage(s)", ref=ref))
        for key, patch_config in stage_patches.items():
            actions.append(Action("PATCH", "__pipeline_stage_automation__", {"config": patch_config},
                                  f"pipeline {name}: set stage {key} automation",
                                  ref=f"{ref}:stage:{key}"))
    return actions


def _plan_routines(cfg, client, root, ids):
    if not cfg.get("routines"):
        return []
    cid = cfg["companyId"]
    live = {r["title"]: r for r in (client.get(f"/api/companies/{cid}/routines") or [])}
    actions = []
    for entry in cfg.get("routines", []):
        existing = live.get(entry["name"])
        if existing is not None:
            actions.extend(_plan_schedule(entry, existing))
            continue
        key = entry.get("assigneeAgent")
        if key is not None and key not in ids and key in _configured_agent_keys(cfg):
            # The assignee is hired in this pass and has no live id yet;
            # main()'s second pass creates the routine. Other routines go on.
            continue
        body = (Path(root) / entry["file"]).read_text()
        assignee = _resolve_agent_ref(ids, key)
        request = {"title": entry["name"], "description": body, "assigneeAgentId": assignee}
        for policy in ("concurrencyPolicy", "catchUpPolicy"):
            if entry.get(policy):
                request[policy] = entry[policy]
        # A new routine has no id yet, so main()'s second pass adds its
        # schedule trigger.
        actions.append(Action("POST", f"/api/companies/{cid}/routines", request,
                              f"routine {entry['name']}: create"))
    return actions


def _plan_schedule(entry, live_routine):
    """A schedule trigger for a live routine whose config names one it lacks."""
    schedule = entry.get("schedule")
    if not schedule:
        return []
    for trigger in live_routine.get("triggers") or []:
        if (trigger.get("kind") == "schedule"
                and trigger.get("cronExpression") == schedule["cronExpression"]
                and trigger.get("timezone") == schedule["timezone"]):
            return []
    body = {"kind": "schedule", "cronExpression": schedule["cronExpression"],
            "timezone": schedule["timezone"], "enabled": True}
    return [Action("POST", f"/api/routines/{live_routine['id']}/triggers", body,
                   f"routine {entry['name']}: schedule {schedule['cronExpression']} {schedule['timezone']}")]


_GOAL_FIELDS = ("description", "level", "status", "ownerAgentId")


def _plan_goals(cfg, client, ids):
    """Create each configured goal missing by title, and patch one that drifted.

    A goal's `ownerAgent` is an agent key. An owner hired in this pass has no
    live id yet, so that goal waits for main()'s second pass, as a routine
    does. A goal on the server that the config does not name is left alone.
    """
    goals = cfg.get("goals")
    if not goals:
        return []
    cid = cfg["companyId"]
    live = {g["title"]: g for g in (client.get(f"/api/companies/{cid}/goals") or [])}
    actions = []
    for goal in goals:
        key = goal.get("ownerAgent")
        if key is not None and key not in ids and key in _configured_agent_keys(cfg):
            continue
        desired = {"title": goal["title"], "description": goal.get("description"),
                   "level": goal.get("level", "team"), "status": goal.get("status", "active"),
                   "ownerAgentId": _resolve_agent_ref(ids, key)}
        existing = live.get(goal["title"])
        if existing is None:
            actions.append(Action("POST", f"/api/companies/{cid}/goals", desired,
                                  f"goal {goal['title']}: create"))
            continue
        diff = _diff({k: desired[k] for k in _GOAL_FIELDS}, existing)
        if diff:
            actions.append(Action("PATCH", f"/api/goals/{existing['id']}", diff,
                                  f"goal {goal['title']}: set {sorted(diff)}"))
    return actions


def plan_actions(cfg, client, root=REPO_ROOT):
    actions = _plan_company(cfg, client)
    live_agents = client.get(f"/api/companies/{cfg['companyId']}/agents")
    ids = agent_ids(cfg, live_agents)
    by_id = {a["id"]: a for a in live_agents}
    pending_hire = False
    for agent in cfg["agents"]:
        aid = ids.get(agent["key"])
        if aid is None:
            actions.append(_plan_new_agent(cfg, agent, root, ids))
            pending_hire = True
        else:
            actions.extend(_plan_existing_agent(cfg, agent, by_id[aid], client, root, ids))
            actions.extend(_plan_assignment_policy(cfg, agent, by_id[aid], ids))
    if not pending_hire:
        # A pipeline's `assigneeAgent` needs a live id for every agent it
        # names. A fresh company hires several agents in one pass; the existing
        # second pass in main() replans once every hire from this pass has
        # landed, so pipeline planning waits for that pass rather than failing
        # on an agent that only exists a few lines up.
        actions.extend(_plan_pipelines(cfg, client, root, ids))
    actions.extend(_plan_routines(cfg, client, root, ids))
    actions.extend(_plan_goals(cfg, client, ids))
    return actions


def run_actions(actions, client, apply, echo=None):
    """Send or describe each action in order. Each line is echoed as it happens,
    so a failure part way through still leaves a record of what landed. A
    pipeline's stage-automation patch carries `f"{pipeline_ref}:stage:{key}"` as
    its own `ref`, so it can find the stage id the pipeline-create response
    returned for that key. A `NOTE` action (a drift report) is never sent
    anywhere; it only prints, in both dry-run and apply mode."""
    lines = []
    pipeline_ids = {}
    stage_ids = {}
    for n, action in enumerate(actions, 1):
        if action.method == "NOTE":
            line = f"drift: {action.summary}"
            lines.append(line)
            if echo:
                echo(line)
            continue
        if apply:
            path = action.path
            if path == "__pipeline_stage_automation__":
                target = stage_ids.get(action.ref)
                if not target:
                    raise PaperclipError(
                        f"no stage id recorded for {action.ref}; the pipeline create response "
                        "must include a stage with this key")
                path = f"/api/pipelines/{target[0]}/stages/{target[1]}"
            try:
                result = client.send(action.method, path, action.body)
            except PaperclipError as err:
                raise PaperclipError(
                    f"{n - 1} of {len(actions)} change(s) applied before this failure: {err}") from err
            note = ""
            if action.path.endswith("/pipelines") and action.ref:
                new_pid = (result or {}).get("id")
                if not new_pid:
                    raise PaperclipError(f"pipeline create for {action.ref} returned no id: {result!r}")
                pipeline_ids[action.ref] = new_pid
                for s in (result or {}).get("stages") or []:
                    skey, sid = s.get("key"), s.get("id")
                    if skey and sid:
                        stage_ids[f"{action.ref}:stage:{skey}"] = (new_pid, sid)
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
                            f"so approve it in the Paperclip interface: {err}") from err
                note = f" (new id {agent.get('id')}; copy it into company.json)"
            line = f"done: {action.summary}{note}"
        else:
            line = f"plan: {action.method} {action.path} :: {action.summary}"
        lines.append(line)
        if echo:
            echo(line)
    return lines


def _summary_line(actions, applied):
    """The final one-line status. Never claims sync when a drift `NOTE` is in
    the plan, and never counts a drift note as a "change" `--apply` would
    send."""
    if not actions:
        return "in sync: nothing to change"
    changes = [a for a in actions if a.method != "NOTE"]
    if not changes or applied:
        return None
    return f"{len(changes)} change(s) planned. Run again with --apply to send them."


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="company.json, or an overlay such as paperclip/orgs/<name>.json")
    parser.add_argument("--apply", action="store_true", help="send the changes; default is a dry run")
    parser.add_argument("--show-bodies", action="store_true", help="print each request body")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    client = Client(cfg["apiBase"])
    root = Path(args.config).resolve().parents[1] if Path(args.config).is_absolute() else REPO_ROOT
    try:
        actions = plan_actions(cfg, client, root)
        if args.show_bodies:
            for a in actions:
                print(f"{a.method} {a.path}\n{json.dumps(a.body, indent=2)}\n")
        run_actions(actions, client, args.apply, echo=print)
        if args.apply and actions:
            # A hire gets a default task-assign grant after creation, and the
            # server refuses a wake prompt on a new agent, so a second pass
            # sets both to what the config says.
            again = plan_actions(cfg, client, root)
            if again:
                print(f"second pass: {len(again)} change(s) the first pass set off")
                run_actions(again, client, True, echo=print)
    except PaperclipError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    line = _summary_line(actions, args.apply)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
