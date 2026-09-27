#!/usr/bin/env python3
"""The only automated stop on a Paperclip team. No model is called.

Paperclip may bill a fleet as `subscription_included`, in which case its dollar
budgets never fire. This script is the brake instead. Each pass it:

1. Pauses an agent that reached its `runsPerDay` cap for the current UTC day.
1b. Pauses an agent that reached its per-adapter cap in `company.json`'s
   `runCaps`, or that runs on an adapter that reached its `harnessTotal` cap.
   An adapter with no entry in `runCaps` uses the `default` entry, so a new
   adapter is never uncapped. Every cap is validated first: a cap of `0` is
   refused rather than read as no cap.
2. Pauses every agent after a burst of authentication failures in the last 15
   minutes, so a dead login does not strand a queue of runs.
3. Holds the approval gate. If an agent assigned an open issue to an agent, the
   issue goes back to the board in `in_review` and the assigning agent is
   paused. Paperclip lets every active agent assign tasks, whatever its
   `canAssignTasks` flag says, so this check is the gate's only enforcement.
   Exempt: a lead's own delegation child (see the note below duty 5).
4. Starts approved work. When the board accepts the scope card that the scoping
   agent raised (a `request_confirmation` on the `scope` document), it assigns
   the lead the scope names and attaches an approval stage with the board as
   the approver, so the delivery comes back for review. When the board rejects
   the card, the ticket goes back to the scoping agent with the reason, and so
   does a comment that supersedes the card. Each card is acted on once. A scope
   card with no `payload.target` starts nothing: the ticket gets one comment
   and the log gets a warning.
5. Parks work that no person asked for. The first time it sees an issue that no
   person created and no routine created, it moves the issue to `backlog`,
   clears the assignee, and adds the `scope-creep` label. An issue is judged
   once. If a person later approves it, the watchdog leaves it alone.

   Exempt from both duty 3 and duty 5: a lead's legitimate delegation child.
   `company.json`'s `watchdog.leadKeys` names which agent keys are leads. A
   child issue passes both checks untouched, and the lead is never paused for
   making it, when its `parentId` names an issue currently assigned to a lead in
   that list, its own assignee's `reportsTo` (in `company.json`) names that same
   lead, AND the one who made it -- the child's `createdByAgentId` for duty 5,
   the agent who set the assignment for duty 3 -- resolves to that same lead
   key. All three must hold together: the first two alone are shape only, and
   any agent could create a child that merely looks like a lead's delegation
   without being one. A child handed to anyone else, hung off a ticket that lead
   does not currently hold, or made by someone other than that lead, gets
   today's treatment. `watchdog.leadKeys` is empty by default, so this changes
   nothing until it is set.

   A second, differently-shaped exemption for the same two duties: a lead's
   `wiki-request` filing to the knowledge office, which reports to the scoping
   agent rather than to the lead, so the `reportsTo` chain above never reaches
   it. This one passes untouched only when all four hold: the child's `parentId`
   names an issue currently assigned to a lead in `watchdog.leadKeys`; the one
   who made the child resolves to that same lead (the same actor check as
   above); the child carries the `wiki-request` label (matched by id against
   `GET /api/companies/{id}/labels`, the label id resolved the same way
   `scope-creep`'s is); and the child's assignee is the agent whose key is
   `watchdog.wikiRequestAssigneeKey`, `knowledge-office` by default. No
   `wiki-request` label on the company makes this always false, the same way an
   empty `leadKeys` does for the first exemption.
6. Guards against a cascade of agent-made work. `company.json`'s
   `watchdog.workerKeys` names which agent keys are workers under the
   delegation flow; a lead is never listed there, because a lead creating child
   issues is the flow working as designed. If a worker creates any issue that is
   not already resting in `backlog` with no assignee, the watchdog pauses that
   worker, the same way it pauses on a run cap. The simpler rule was chosen over
   inferring "worker" from `reportsTo` and `canAssignTasks`, because an explicit
   list is what a test can pin down and what a config reader can see at a
   glance. This runs alongside duty 5, not instead of it: duty 5 still parks the
   issue itself; this duty stops the worker that made it. Judged once, on the
   `seen` set duty 5 already maintains: an issue a worker filed compliantly is
   never re-read on a later pass just because someone else reassigned or started
   it since.
7. Swaps a lead's open work to its standby twin. An agent whose config carries
   `twinOf` is a twin of the lead that key names; a company with no such agent
   behaves exactly as it did before this duty existed. With no active swap for a
   lead, this reads its two newest heartbeat runs with a terminal status of
   `succeeded` or `failed` (`cancelled`, `interrupted`, `queued`, and `running`
   are ignored, because none of them says whether the model actually ran). If
   both are `failed` and both finished within `SWAP_FAILURE_WINDOW` (30 minutes)
   of now, it resumes the twin, pauses the lead, and reassigns each of the
   lead's open issues (`todo`, `in_progress`, `blocked`) to the twin, with one
   comment on each naming both agents, a sanitized code for each of the two
   failures (never the run's free-text `error`, which is untrusted adapter
   output another agent reads), and the swap-back time. A run with no readable
   timestamp counts as outside the window, so it never triggers a swap. The swap
   is recorded, by lead, in the state file's `swaps` key, and revalidated
   against the live config and agent ids every tick before anything acts on it.
   Once a swap is `SWAP_BACK_AFTER` (5 hours) old, it starts swapping back,
   marked `phase: "returning"`: the lead resumes, the twin pauses, and every
   issue still on the twin from that swap moves back, with one comment each.
   While a cap pause still binds the lead, swap-back does not start at all; the
   twin keeps the work, the swap stays recorded, and one warning names the lead
   and the cap each tick, until the cap clears. Once started, the swap is not
   cleared from state until a later tick confirms, from live state, that the
   lead is resumed, the twin is paused, and no issue from the swap is still on
   the twin; a failed resume, pause, or issue PATCH (a 409, another run holds
   the checkout, included) is a warning, not a crash, and is retried on the next
   tick by re-reading live state, never by looping in place.

    python3 scripts/paperclip-watchdog.py --dry-run   # print, change nothing
    python3 scripts/paperclip-watchdog.py             # act and log

A cap-paused agent never resumes on its own. There is no new-day resume here, so
a fleet-total pause stops every agent and waits for a person. Resume a paused
agent from the Paperclip interface, or with `POST /api/agents/{id}/resume`.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    validate_run_caps,
)

AUTH_WINDOW = timedelta(minutes=15)
CLOSED = {"done", "cancelled"}
GATED = {"todo", "in_progress", "blocked"}
SCOPE_CREEP = "scope-creep"
WIKI_REQUEST_LABEL = "wiki-request"
WIKI_REQUEST_ASSIGNEE_KEY = "knowledge-office"
SCOPE_KEY = "scope"
LEAD_LINE = re.compile(r"^[\s>*_-]*Lead[*_]*\s*:[\s*_`]*([A-Za-z-]+)", re.MULTILINE | re.IGNORECASE)
FINISHED_RUN_STATUSES = {"succeeded", "failed"}
SWAP_BACK_AFTER = timedelta(hours=5)
SWAP_FAILURE_WINDOW = timedelta(minutes=30)
_PAUSE_PATH = re.compile(r"^/api/agents/([^/]+)/pause$")


@dataclass
class Decision:
    actions: list = field(default_factory=list)
    seen: set = field(default_factory=set)
    warnings: list = field(default_factory=list)
    swaps: dict = field(default_factory=dict)


def parse_ts(value):
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _ts(record):
    """The record's createdAt, or None when it is missing or malformed."""
    try:
        return parse_ts(record["createdAt"])
    except (KeyError, TypeError, ValueError):
        return None


def _pauses(cfg, runs, live_agents, now, warnings):
    """The per-day `runsPerDay` cap, and the authentication-failure burst.

    A cap pause is one way: nothing here, and nothing anywhere else in this
    script, ever resumes a capped agent. There is no new-day resume, so a
    fleet-total pause stops every agent and waits for a person.
    """
    validate_run_caps(cfg)
    ids = agent_ids(cfg, live_agents)
    status = {a["id"]: a.get("status") for a in live_agents}
    reasons = {}
    for agent in cfg["agents"]:
        if agent["key"] not in ids:
            warnings.append(f"no live agent for {agent['name']!r}; it has no run cap")

    # A run with a bad timestamp counts toward today's cap. Dropping it is the
    # direction that lets runs go unbounded.
    today = now.date()
    for agent in cfg["agents"]:
        aid, cap = ids.get(agent["key"]), agent.get("runsPerDay")
        # `not cap` is why a cap of `0` would read as "no cap configured" here.
        # `validate_run_caps` above refuses a `0` so this guard only ever means
        # "no cap set".
        if aid is None or not cap:
            continue
        count = _count_runs_today(runs, aid, today)
        if count >= cap:
            reasons[aid] = f"{agent['name']}: {count} runs today, cap {cap}"

    wd = cfg.get("watchdog", {})
    pattern = wd.get("authFailurePattern", "OAuth session expired")
    burst = wd.get("authFailureBurst", 3)
    recent = []
    for r in runs:
        ts = _ts(r)
        if ts and r.get("status") == "failed" and pattern in (r.get("error") or "") and now - ts <= AUTH_WINDOW:
            recent.append(r)
    if len(recent) >= burst:
        for agent in cfg["agents"]:
            aid = ids.get(agent["key"])
            if aid is not None:
                reasons.setdefault(aid, f"{agent['name']}: {len(recent)} auth failures in 15 minutes")

    return [
        Action("POST", f"/api/agents/{aid}/pause", None, f"pause {why}")
        for aid, why in reasons.items()
        if status.get(aid) != "paused"
    ]


def _count_runs_today(runs, aid, today):
    """A run with a bad timestamp counts toward today's cap. Dropping it is the
    direction that lets runs go unbounded."""
    count = 0
    for r in runs:
        if r.get("agentId") != aid:
            continue
        ts = _ts(r)
        if ts is None or ts.date() == today:
            count += 1
    return count


def _run_cap_breaker_pauses(cfg, runs, live_agents, now, warnings):
    """A cap per agent per adapter, and a total per adapter, both keyed by
    `adapterType` in `company.json`'s `runCaps`. An adapter with no entry falls
    back to `runCaps["default"]`, so a new adapter is never uncapped. A missing
    `"default"` entry is a config error, not a quiet no-op: it would leave the
    fallback path with no cap at all, so it raises instead. This runs alongside
    `_pauses`, not instead of it, which keeps that function's per-agent
    `runsPerDay` cap as a second, independent backstop.

    Every guard below tests a cap for truthiness, so a cap of `0` would read as
    "no cap configured" and enforce nothing, silently. `validate_run_caps`
    refuses a `0` before any of that, which is why `if agent_cap and ...` is
    safe to write. No example, default, or template value may be `0`.

    Like `_pauses`, this only ever pauses. A cap-paused agent never resumes on
    its own.
    """
    validate_run_caps(cfg)
    caps = cfg.get("runCaps")
    if not caps:
        return []
    ids = agent_ids(cfg, live_agents)
    by_aid = {a["id"]: a for a in live_agents}
    configured = {}
    for agent in cfg["agents"]:
        aid = ids.get(agent["key"])
        if aid is None:
            warnings.append(f"no live agent for {agent['name']!r}; it has no run-cap breaker coverage")
            continue
        configured[aid] = agent
    today = now.date()

    # Every live agent counts toward its adapter's total, configured in
    # `company.json` or not, so an agent nobody added there still counts against
    # `harnessTotal` instead of running past it unseen.
    by_adapter = {}
    for live in live_agents:
        adapter = live.get("adapterType", "claude_local")
        by_adapter.setdefault(adapter, []).append(live["id"])

    reasons = {}
    for adapter, live_ids in by_adapter.items():
        cap_entry = caps.get(adapter)
        if cap_entry is None:
            cap_entry = caps.get("default")
            if cap_entry is None:
                raise PaperclipError(
                    f"runCaps has no entry for adapter {adapter!r} and no \"default\" entry to fall back to")
            warnings.append(f"adapter {adapter!r} has no runCaps entry; using \"default\"")
        per_agent_caps = cap_entry.get("agents", {})
        total_cap = cap_entry.get("harnessTotal")
        total = 0
        for aid in live_ids:
            count = _count_runs_today(runs, aid, today)
            total += count
            agent = configured.get(aid)
            agent_cap = per_agent_caps.get(agent["key"]) if agent else None
            if agent_cap and count >= agent_cap:
                reasons[aid] = f"{agent['name']}: {count} runs today on {adapter}, cap {agent_cap}"
        if total_cap and total >= total_cap:
            for aid in live_ids:
                agent = configured.get(aid)
                name = agent["name"] if agent else by_aid[aid].get("name", aid)
                reasons.setdefault(aid,
                                   f"{name}: {total} runs today on {adapter}, cap {total_cap} for the adapter")

    return [
        Action("POST", f"/api/agents/{aid}/pause", None, f"pause {why}")
        for aid, why in reasons.items()
        if by_aid.get(aid, {}).get("status") != "paused"
    ]


def _worker_pauses(cfg, issues, live_agents, seen, warnings):
    """Pause a worker agent the moment it creates an issue that is not already
    resting in `backlog` with no assignee. `company.json`'s
    `watchdog.workerKeys` lists which agent keys are workers; a key with no live
    match only warns, the same as the run-cap breaker does for an unmatched
    agent. `decide` runs this alongside `_park`, which still parks the issue
    itself on the same pass.

    Judged once, using the same `seen` set `_park` already marks every non-user,
    non-routine issue into on the first pass that reaches it (whether or not
    `_park` takes any action): an issue already in `seen` is skipped here
    entirely. Without this, a worker's compliant backlog filing -- correctly
    unassigned, so no pause today -- would read as a violation on a later pass
    the moment anyone else assigned or started it, pausing the worker for
    someone else's later action rather than its own. This does not reconstruct
    the issue's state at the moment of creation; a reassignment that lands
    before the very first pass ever observes the issue is still judged by that
    state, same as `_park`'s own judged-once limit."""
    keys = cfg.get("watchdog", {}).get("workerKeys") or []
    if not keys:
        return []
    ids = agent_ids(cfg, live_agents)
    status = {a["id"]: a.get("status") for a in live_agents}
    worker_names = {}
    for agent in cfg["agents"]:
        if agent["key"] not in keys:
            continue
        aid = ids.get(agent["key"])
        if aid is None:
            warnings.append(f"no live agent for {agent['name']!r}; it has no worker-issue guard coverage")
            continue
        worker_names[aid] = agent["name"]
    if not worker_names:
        return []
    reasons = {}
    for issue in issues:
        if issue.get("id") in seen:
            continue
        creator = issue.get("createdByAgentId")
        if creator not in worker_names:
            continue
        if issue.get("status") == "backlog" and not issue.get("assigneeAgentId") \
                and not issue.get("assigneeUserId"):
            continue
        name = issue.get("identifier") or issue["id"]
        reasons.setdefault(creator, f"{worker_names[creator]}: created issue {name}, "
                                    "which a worker must never do")
    return [
        Action("POST", f"/api/agents/{aid}/pause", None, f"pause {why}")
        for aid, why in reasons.items()
        if status.get(aid) != "paused"
    ]


def _is_delegated_child(cfg, issue, by_id, id_to_key, reports_to, actor_key):
    """True for a lead's legitimate delegation child: `issue`'s `parentId` names
    an issue currently assigned to an agent whose key is in
    `watchdog.leadKeys`; `issue`'s own assignee's `reportsTo` (in
    `company.json`) names that same lead key; and `actor_key` -- the key of
    whoever created the issue (`_park`) or made the assignment (`_gate`) -- IS
    that same lead key. All three must hold together. Shape alone is not
    enough: any agent could create a child under a lead's ticket and assign it
    to that lead's worker, so the actor is checked too, not just the structure.
    A child handed to anyone else, hung off a ticket that lead does not
    currently hold, or made by someone other than that lead, is not exempt."""
    lead_keys = set(cfg.get("watchdog", {}).get("leadKeys") or [])
    if not lead_keys:
        return False
    parent = by_id.get(issue.get("parentId"))
    if not parent:
        return False
    parent_key = id_to_key.get(parent.get("assigneeAgentId"))
    if parent_key not in lead_keys or actor_key != parent_key:
        return False
    child_key = id_to_key.get(issue.get("assigneeAgentId"))
    if not child_key:
        return False
    return reports_to.get(child_key) == parent_key


HANDED_BACK = {"in_review", "done"}


def _handed_back(issue):
    """True when a lead handed `issue` to a person at the end of its run: no
    agent assignee, a user assignee, and status `in_review` or `done`."""
    return (not issue.get("assigneeAgentId") and bool(issue.get("assigneeUserId"))
            and issue.get("status") in HANDED_BACK)


def _filed_from_run_on(issue, parent, origin_runs, id_to_key):
    """The agent key of the run that created `issue`, when that run was woken for
    `parent`. None when the run is unknown, its snapshot is unreadable, or it
    was woken for a different issue."""
    run = origin_runs.get(issue.get("originRunId"))
    if not run:
        return None
    snapshot = run.get("contextSnapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except ValueError:
            return None
    if not isinstance(snapshot, dict) or snapshot.get("issueId") != parent.get("id"):
        return None
    return id_to_key.get(run.get("agentId"))


def _is_wiki_request_child(cfg, issue, by_id, id_to_key, wiki_label_id, actor_key, origin_runs=None):
    """True for a lead's `wiki-request` filing to the knowledge office, a
    companion path that does not fit `_is_delegated_child` because that agent
    reports to the scoping agent, not to any lead. All four must hold: `issue`'s
    `parentId` names an issue currently assigned to a lead in
    `watchdog.leadKeys`; `actor_key` -- the key of whoever created the issue
    (`_park`) or made the assignment (`_gate`) -- IS that same lead key, the
    same actor check `_is_delegated_child` makes, for the same reason: shape
    alone does not prove who acted; `issue` carries the label whose id is
    `wiki_label_id` (read from `labelIds`, resolved against
    `GET /api/companies/{id}/labels` the way `main` already resolves
    `scope-creep` -- no live issue has been seen carrying an embedded
    `labels: [{name: ...}]` shape, so this reads the id-list form); and
    `issue`'s assignee is the agent whose key is
    `watchdog.wikiRequestAssigneeKey`, `knowledge-office` by default.
    `wiki_label_id` is `None` when the company has no such label, which makes
    this always `False` rather than raising.

    A parent the lead already handed back also counts: no agent assignee, a user
    assignee, and status `in_review` or `done`. A wake prompt that makes every
    lead end its run that way would otherwise lose a `wiki-request` its
    exemption the moment its lead finished. A handed-back parent names no
    holder, so the proof comes from the child instead: its `originRunId` must be
    a run of the actor, woken for that parent. Another lead's handed-back ticket
    fails that check. A run outside `origin_runs` fails it too, so the issue is
    parked rather than exempted."""
    if wiki_label_id is None:
        return False
    wcfg = cfg.get("watchdog", {})
    lead_keys = set(wcfg.get("leadKeys") or [])
    if not lead_keys:
        return False
    parent = by_id.get(issue.get("parentId"))
    if not parent:
        return False
    parent_key = id_to_key.get(parent.get("assigneeAgentId"))
    if parent_key is None and _handed_back(parent) and \
            _filed_from_run_on(issue, parent, origin_runs or {}, id_to_key) == actor_key:
        parent_key = actor_key
    if parent_key not in lead_keys or actor_key != parent_key:
        return False
    if wiki_label_id not in (issue.get("labelIds") or []):
        return False
    assignee_key = wcfg.get("wikiRequestAssigneeKey", WIKI_REQUEST_ASSIGNEE_KEY)
    return id_to_key.get(issue.get("assigneeAgentId")) == assignee_key


def _delegation_maps(cfg, issues, live_agents):
    by_id = {i["id"]: i for i in issues}
    id_to_key = {v: k for k, v in agent_ids(cfg, live_agents).items()}
    reports_to = {a["key"]: a.get("reportsTo") for a in cfg["agents"]}
    return by_id, id_to_key, reports_to


def _park(cfg, issues, live_agents, seen, label_id, wiki_label_id=None, origin_runs=None):
    by_id, id_to_key, reports_to = _delegation_maps(cfg, issues, live_agents)
    actions, judged = [], set()
    for issue in issues:
        iid = issue["id"]
        if iid in seen or issue.get("createdByUserId") or issue.get("originKind") == "routine_execution":
            continue
        creator_key = id_to_key.get(issue.get("createdByAgentId"))
        if _is_delegated_child(cfg, issue, by_id, id_to_key, reports_to, creator_key) or \
                _is_wiki_request_child(cfg, issue, by_id, id_to_key, wiki_label_id, creator_key, origin_runs):
            judged.add(iid)
            continue
        judged.add(iid)
        if issue.get("status") in CLOSED:
            continue
        body = {}
        if issue.get("status") != "backlog" or issue.get("assigneeAgentId") or issue.get("assigneeUserId"):
            body = {"status": "backlog", "assigneeAgentId": None, "assigneeUserId": None}
        labels = list(issue.get("labelIds") or [])
        if label_id not in labels:
            body["labelIds"] = labels + [label_id]
        if body:
            name = issue.get("identifier") or iid
            actions.append(Action("PATCH", f"/api/issues/{iid}", body, f"park {name} as scope creep", ref=iid))
    return actions, judged


def gate_candidates(issues):
    """Open issues an agent holds. Only these need their assignment history read."""
    return [i for i in issues if i.get("assigneeAgentId") and i.get("status") in GATED]


def _gate(cfg, issues, activity, live_agents, wiki_label_id=None, origin_runs=None):
    """Send back each open issue whose current agent assignment an agent made.

    `activity` maps an issue id to its events, newest first, as
    `GET /api/issues/{id}/activity` returns them.
    """
    board = cfg.get("watchdog", {}).get("boardUserId", "local-board")
    names = {a["id"]: a.get("name", a["id"]) for a in live_agents}
    status = {a["id"]: a.get("status") for a in live_agents}
    by_id, id_to_key, reports_to = _delegation_maps(cfg, issues, live_agents)
    actions, pausing = [], []
    for issue in gate_candidates(issues):
        iid, holder = issue["id"], issue["assigneeAgentId"]
        assigned = next(
            (e for e in activity.get(iid, [])
             if ((e.get("details") or {}).get("changes") or {}).get("assigneeAgentId", {}).get("to") == holder),
            None,
        )
        if not assigned or assigned.get("actorType") != "agent":
            continue
        actor = assigned.get("actorId")
        actor_key = id_to_key.get(actor)
        if _is_delegated_child(cfg, issue, by_id, id_to_key, reports_to, actor_key) or \
                _is_wiki_request_child(cfg, issue, by_id, id_to_key, wiki_label_id, actor_key, origin_runs):
            continue
        name = issue.get("identifier") or iid
        actions.append(Action("PATCH", f"/api/issues/{iid}", {
            "status": "in_review", "assigneeAgentId": None, "assigneeUserId": board,
            "comment": f"Watchdog: {names.get(actor, actor)} assigned this to {names.get(holder, holder)} "
                       "without board approval. Sent back for your decision.",
        }, f"send {name} back: {names.get(actor, actor)} assigned it to {names.get(holder, holder)}", ref=iid))
        if actor in names and status.get(actor) != "paused" and actor not in pausing:
            pausing.append(actor)
            actions.append(Action("POST", f"/api/agents/{actor}/pause", None,
                                  f"pause {names[actor]}: assigned {name} without approval"))
    return actions


def approval_candidates(issues, board="local-board"):
    """Tickets waiting on a person before any lead started: in review, held by
    the board, and with no approval stage yet. A stage means the watchdog
    already started the lead, so the ticket is a delivery under review, not a
    scope."""
    return [
        i for i in issues
        if i.get("status") == "in_review" and i.get("assigneeUserId") == board
        and not i.get("assigneeAgentId") and not i.get("policyUnread")
        and not ((i.get("executionPolicy") or {}).get("stages"))
    ]


def attach_policies(client, issues, board, lines, stamp):
    """Read the execution policy of each ticket held by the board in review.

    The company issue list returns `executionPolicy` as null even when a stage
    is set, so `approval_candidates` cannot tell a waiting scope from a delivery
    under review. `GET /api/issues/{id}` carries the real policy. A ticket whose
    read fails is left out of the approvals for this pass."""
    out = []
    for i in issues:
        if i.get("status") == "in_review" and i.get("assigneeUserId") == board \
                and not i.get("assigneeAgentId"):
            try:
                i = {**i, "executionPolicy": client.get(f"/api/issues/{i['id']}").get("executionPolicy")}
            except PaperclipError as err:
                lines.append(f"{stamp} warning: could not read the policy of issue {i['id']}: {err}")
                i = {**i, "policyUnread": True}
        out.append(i)
    return out


def _scope_cards(interactions):
    return [
        x for x in interactions
        if x.get("kind") == "request_confirmation"
        and (((x.get("payload") or {}).get("target") or {}).get("key") == SCOPE_KEY)
    ]


def _untargeted_scope_cards(interactions):
    """Scope cards, known by the scoping agent's `scope:` idempotency key, that
    carry no `payload.target`. The server drops a `target` sent beside
    `payload`, so these cards can never be matched to a scope revision."""
    return [
        x for x in interactions
        if x.get("kind") == "request_confirmation"
        and (x.get("idempotencyKey") or "").startswith(f"{SCOPE_KEY}:")
        and not (x.get("payload") or {}).get("target")
    ]


def parse_lead(body):
    match = LEAD_LINE.search(body or "")
    return match.group(1).lower() if match else None


def _approvals(cfg, issues, interactions, documents, seen, live_agents, warnings):
    """Act on the newest resolved scope card of each waiting ticket.

    `interactions` maps an issue id to `GET /api/issues/{id}/interactions`.
    `documents` maps an issue id to `GET /api/issues/{id}/documents`, fetched
    only for tickets with an accepted card. `seen` holds `ix:<id>` for each card
    already acted on. Each action's `ref` is that `ix:` key, so a failed send
    leaves the card to be tried again on the next pass. A hold, where the
    watchdog only comments, is keyed `ix:<id>:hold:<reason>`. The same hold is
    not repeated, and a fixed cause, such as a new lead in company.json, lets
    the card through on the next pass.
    """
    wcfg = cfg.get("watchdog", {})
    board = wcfg.get("boardUserId", "local-board")
    ids = agent_ids(cfg, live_agents)
    names = {a["id"]: a.get("name", a["id"]) for a in live_agents}
    leads = wcfg.get("leads", {})
    scoper = ids.get(wcfg.get("scopeAgent", "scoper"))
    actions = []
    for issue in approval_candidates(issues, board):
        iid = issue["id"]
        name = issue.get("identifier") or iid
        cards = _scope_cards(interactions.get(iid, []))
        if not cards:
            loose = _untargeted_scope_cards(interactions.get(iid, []))
            if loose and not any(c.get("status") == "pending" for c in loose):
                card = max(loose, key=lambda c: c.get("resolvedAt") or c.get("createdAt") or "")
                ref = f"ix:{card['id']}:hold:no-target"
                if ref not in seen:
                    text = (f"scope card {card['id']} has no target, so it cannot be matched to a scope "
                            "revision. Nothing started. Assign the lead by hand, or have the scoping agent "
                            "raise the card again with `target` inside `payload`.")
                    warnings.append(f"{name}: {text}")
                    actions.append(Action("PATCH", f"/api/issues/{iid}", {"comment": f"Watchdog: {text}"},
                                          f"hold {name}: {text}", ref=ref))
            continue
        if any(c.get("status") == "pending" for c in cards):
            continue
        card = max(cards, key=lambda c: c.get("resolvedAt") or c.get("createdAt") or "")
        key = f"ix:{card['id']}"
        outcome = (card.get("result") or {}).get("outcome") or card.get("status")
        if key in seen:
            continue
        if outcome not in ("accepted", "rejected", "superseded_by_comment"):
            warnings.append(f"{name}: scope card {card['id']} ended as {outcome!r}; nothing started")
            continue
        path = f"/api/issues/{iid}"

        def hold(code, text):
            if f"{key}:hold:{code}" not in seen:
                actions.append(Action("PATCH", path, {"comment": f"Watchdog: {text}"},
                                      f"hold {name}: {text}", ref=f"{key}:hold:{code}"))
        if outcome != "accepted":
            reason = (card.get("result") or {}).get("reason") or (
                "see the board's latest comment." if outcome == "superseded_by_comment" else "no reason given.")
            if not scoper:
                hold("no-scoper", "the scope was rejected, but the scoping agent is not in company.json. "
                                  "Reassign it by hand.")
                continue
            actions.append(Action("PATCH", path, {
                "status": "todo", "assigneeUserId": None, "assigneeAgentId": scoper,
                "comment": f"Scope changes requested by the board: {reason}",
            }, f"return {name} to {names.get(scoper, scoper)}: scope rejected", ref=key))
            continue
        target = (card.get("payload") or {}).get("target") or {}
        scope = next((d for d in documents.get(iid, []) if d.get("key") == SCOPE_KEY), None)
        code = problem = None
        lead_key = parse_lead(scope.get("body")) if scope else None
        lead = ids.get(leads.get(lead_key, "")) if lead_key else None
        if not scope:
            code, problem = "no-scope", "the scope document is missing"
        elif not target.get("revisionId"):
            code, problem = "no-revision", ("the card names no scope revision, so the approval cannot be "
                                            "matched to it")
        elif scope.get("latestRevisionId") != target.get("revisionId"):
            code, problem = "stale", ("the scope changed after the card was raised, so the approval does not "
                                      "cover it")
        elif not lead:
            code = f"lead-{lead_key or 'missing'}"
            problem = f"the scope's Lead line ({lead_key or 'missing'}) names no lead in company.json"
        if problem:
            hold(code, f"approval noted, but {problem}. Nothing started. Assign the lead by hand.")
            continue
        actions.append(Action("PATCH", path, {
            "status": "todo", "assigneeUserId": None, "assigneeAgentId": lead,
            "executionPolicy": {"stages": [{"type": "approval",
                                            "participants": [{"type": "user", "userId": board}]}]},
            "comment": f"Scope approved by the board. Started {names.get(lead, lead)}. "
                       "The delivery comes back to the board for approval.",
        }, f"start {name}: scope approved, assigned {names.get(lead, lead)}", ref=key))
    return actions


def _twin_pairs(cfg):
    """{lead key: twin key}, one entry per agent whose config names `twinOf`.

    Empty on a company with no twins: nothing below this function runs a single
    check when the dict is empty.
    """
    return {a["twinOf"]: a["key"] for a in cfg.get("agents", []) if a.get("twinOf")}


def _newest_finished_runs(runs, aid, n=2):
    """The `n` most recent heartbeat runs for `aid` with a terminal status of
    `succeeded` or `failed`, newest first. `cancelled`, `interrupted`, `queued`,
    and `running` runs are dropped entirely: none of them says whether the model
    actually turned a wheel, so none can stand in for a real failure. Runs sort
    by `finishedAt`, then by `createdAt` when a run has no readable finish time.
    A run with neither sorts as the oldest."""
    finished = [r for r in runs if r.get("agentId") == aid and r.get("status") in FINISHED_RUN_STATUSES]
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    finished.sort(key=lambda r: _finished_ts(r) or _ts(r) or epoch, reverse=True)
    return finished[:n]


def _finished_ts(run):
    """The run's finishedAt, or None when it is missing or malformed."""
    try:
        return parse_ts(run["finishedAt"])
    except (KeyError, TypeError, ValueError):
        return None


def _in_failure_window(ts, now):
    """True when `ts` is readable, not in the future, and at most
    `SWAP_FAILURE_WINDOW` before `now`. The caller passes the run's
    `finishedAt`, because a lead run can last up to an hour and its start says
    nothing about when it failed. A missing or malformed timestamp (`None`) and
    a future one are both outside the window, so neither counts toward a swap. A
    run exactly `SWAP_FAILURE_WINDOW` old counts as inside."""
    return ts is not None and timedelta(0) <= now - ts <= SWAP_FAILURE_WINDOW


_ERROR_CODE_SANITIZE = re.compile(r"[^a-z0-9_]+")


def _run_failure_code(run):
    """A safe, short label for a run's failure, fit to put in a comment another
    agent reads: `errorCode` only, lowercased and reduced to `[a-z0-9_]`, capped
    at 64 characters. `error` is never read here: it is free text from the
    adapter, untrusted, and could carry anything up to something crafted to look
    like an instruction to whoever reads the comment next. Empty or absent after
    sanitizing, this names the run instead of guessing at what went wrong."""
    code = _ERROR_CODE_SANITIZE.sub("_", (run.get("errorCode") or "").strip().lower()).strip("_")[:64]
    if code:
        return code
    return f"no error code (run {run.get('id') or 'unknown'})"


def _paused_targets(actions):
    """Every agent id a pause `Action` list already targets, read back off each
    action's own path rather than threaded through as a second value, so a
    swap-back can tell a lead the cap breaker paused this same pass apart from
    one it is free to resume."""
    out = set()
    for a in actions:
        m = _PAUSE_PATH.match(a.path)
        if m:
            out.add(m.group(1))
    return out


def _capped_now(cfg, runs, live_agents, now):
    """Every agent id a run-cap pause (the per-day cap or the adapter breaker)
    would target this pass, judged as if nothing were paused yet, mapped to that
    pause action's own reason text.

    `_pauses` and `_run_cap_breaker_pauses` both go silent for an agent already
    showing `status: paused`, which every lead mid-swap already does. A swap-back
    needs to know whether the cap still binds a lead regardless, so this re-runs
    both against a copy of `live_agents` with every status forced to `"idle"`,
    and reads the pause targets, and why, off that."""
    idle_view = [{**a, "status": "idle"} for a in live_agents]
    scratch = []
    reasons = (_pauses(cfg, runs, idle_view, now, scratch)
               + _run_cap_breaker_pauses(cfg, runs, idle_view, now, scratch))
    out = {}
    for a in reasons:
        m = _PAUSE_PATH.match(a.path)
        if m:
            out.setdefault(m.group(1), a.summary[len("pause "):] if a.summary.startswith("pause ")
                           else a.summary)
    return out


def _validated_swaps(cfg, swaps, ids, warnings):
    """Drop any persisted swap entry that no longer matches this tick's
    configured twin pairs or live agent ids, before anything acts on it.

    The state file is this script's own output, but it is read back untrusted
    the same way any file on disk is: a hand edit, a config that has since
    dropped a twin, or the ids simply drifting out from under a stale entry are
    all indistinguishable from an honest record once it is parsed back into a
    dict. Nothing here is acted on until it is confirmed against
    `_twin_pairs(cfg)` and the live agent ids for this tick.
    """
    pairs = _twin_pairs(cfg)
    valid = {}
    for lead_key, swap in swaps.items():
        twin_key = pairs.get(lead_key)
        if twin_key is None:
            warnings.append(f"swap state names {lead_key!r}, which is not a configured twin pair; dropping it")
            continue
        if swap.get("twinKey") != twin_key:
            warnings.append(f"swap state for {lead_key!r} names twin {swap.get('twinKey')!r}, "
                            f"not the configured {twin_key!r}; dropping it")
            continue
        if ids.get(lead_key) != swap.get("leadId") or ids.get(twin_key) != swap.get("twinId"):
            warnings.append(f"swap state for {lead_key!r} does not match live agent ids; dropping it")
            continue
        valid[lead_key] = swap
    return valid


def _due_swap_keys(swaps, now):
    """Every lead key whose swap is `SWAP_BACK_AFTER` old or more, or already
    mid-return. Used only to tell `_swap_out` which leads to leave alone this
    tick, so its maintenance never fights `_swap_back`'s own actions on the same
    lead in the same pass."""
    due = set()
    for lead_key, swap in swaps.items():
        if swap.get("phase") == "returning":
            due.add(lead_key)
            continue
        try:
            started_ts = parse_ts(swap["startedAt"])
        except (KeyError, TypeError, ValueError):
            continue
        if now - started_ts >= SWAP_BACK_AFTER:
            due.add(lead_key)
    return due


def _swap_out(cfg, runs, issues, live_agents, swaps, now, warnings, due_keys=frozenset()):
    """New swaps, and a retry of any issue a previous swap's PATCH failed to
    move. A lead already in `swaps` is not re-judged against its runs again;
    only its still-unmoved issues (still assigned to the lead, per live state)
    are retried, by re-reading that state fresh, never by looping in place. A
    lead in `due_keys` is left entirely alone here: `_swap_back` is handling it
    this tick, and a straggler issue must never be moved onto the twin in the
    same pass that is trying to move everything off it. A new swap fires only
    when the lead's two newest finished runs both failed and both finished
    within `SWAP_FAILURE_WINDOW` of `now`; a run with no readable timestamp
    counts as outside the window. This stops a swap on stale failure history,
    from long before the watchdog started watching this lead.
    Returns (actions, the next `swaps` dict)."""
    pairs = _twin_pairs(cfg)
    if not pairs and not swaps:
        return [], dict(swaps)
    ids = agent_ids(cfg, live_agents)
    names = {a["id"]: a.get("name", a["id"]) for a in live_agents}
    status = {a["id"]: a.get("status") for a in live_agents}
    by_id = {i["id"]: i for i in issues}
    actions = []
    next_swaps = dict(swaps)

    for lead_key, twin_key in pairs.items():
        if lead_key in due_keys:
            continue
        if lead_key in swaps:
            swap = swaps[lead_key]
            lead_id = swap.get("leadId")
            twin_id = swap.get("twinId")
            if status.get(lead_id) != "paused":
                actions.append(Action("POST", f"/api/agents/{lead_id}/pause", None,
                                      f"pause {names.get(lead_id, lead_key)}: swapped to "
                                      f"{names.get(twin_id, swap.get('twinKey', twin_key))}"))
            if status.get(twin_id) == "paused":
                actions.append(Action("POST", f"/api/agents/{twin_id}/resume", None,
                                      f"resume {names.get(twin_id, swap.get('twinKey', twin_key))}: "
                                      f"swap in for {names.get(lead_id, lead_key)}"))
            for iid in swap.get("issueIds", []):
                issue = by_id.get(iid)
                if issue is None or issue.get("assigneeAgentId") != lead_id \
                        or issue.get("status") not in GATED:
                    continue
                name = issue.get("identifier") or iid
                actions.append(Action("PATCH", f"/api/issues/{iid}", {
                    "assigneeAgentId": twin_id,
                    "comment": f"Watchdog: retrying the swap to {names.get(twin_id, twin_key)}.",
                }, f"retry reassign {name} to {names.get(twin_id, twin_key)}", ref=f"swap:{lead_key}:{iid}"))
            continue

        lead_id, twin_id = ids.get(lead_key), ids.get(twin_key)
        if lead_id is None or twin_id is None:
            warnings.append(f"twin pair {lead_key!r}/{twin_key!r} has no live match for one side; "
                            "skipping the swap check")
            continue
        newest = _newest_finished_runs(runs, lead_id, 2)
        if len(newest) < 2 or any(r.get("status") != "failed" for r in newest):
            continue
        if any(not _in_failure_window(_finished_ts(r), now) for r in newest):
            continue
        codes = [_run_failure_code(r) for r in newest]
        lead_name, twin_name = names.get(lead_id, lead_key), names.get(twin_id, twin_key)
        lead_issues = [i for i in issues if i.get("assigneeAgentId") == lead_id and i.get("status") in GATED]
        moved_ids = [i["id"] for i in lead_issues]
        swap_back_at = now + SWAP_BACK_AFTER
        actions.append(Action("POST", f"/api/agents/{twin_id}/resume", None,
                              f"resume {twin_name}: two failed runs by {lead_name}"))
        actions.append(Action("POST", f"/api/agents/{lead_id}/pause", None,
                              f"pause {lead_name}: swapped to {twin_name}"))
        for issue in lead_issues:
            name = issue.get("identifier") or issue["id"]
            comment = (f"Watchdog: {lead_name} failed its last two runs ({codes[1]}, then {codes[0]}). "
                       f"Moved to {twin_name} until {swap_back_at.isoformat(timespec='seconds')}.")
            actions.append(Action("PATCH", f"/api/issues/{issue['id']}",
                                  {"assigneeAgentId": twin_id, "comment": comment},
                                  f"reassign {name} from {lead_name} to {twin_name}",
                                  ref=f"swap:{lead_key}:{issue['id']}"))
        next_swaps[lead_key] = {"twinKey": twin_key, "leadId": lead_id, "twinId": twin_id,
                                "startedAt": now.isoformat(timespec="seconds"), "issueIds": moved_ids}
    return actions, next_swaps


def _swap_back(cfg, live_agents, issues, swaps, now, warnings, capped_aids):
    """Every swap whose `startedAt` is `SWAP_BACK_AFTER` old or more, ended,
    subject to one hold: `capped_aids` maps an agent id to the reason a run cap
    would pause it right now, judged as if nothing were paused (see
    `_capped_now`). While the lead's id is in there and the swap has not yet
    started returning, the swap-back does not start at all this tick: the twin
    keeps the work, the entry is untouched, and one warning names the lead and
    the cap. It starts on the first tick the cap no longer binds. A cap-paused
    agent never resumes on its own, and this is the one place that reads a cap
    to decide whether it may resume a lead, so the cap always wins.

    Once started, the swap is marked `phase: "returning"` and is not cleared
    from state until a later tick confirms, from live state, that the lead is no
    longer paused, the twin is paused, and no gated issue from the swap is still
    on the twin. A resume, a pause, or an issue PATCH that fails this tick
    leaves that piece undone and the entry in place, so the next tick re-reads
    live state and retries only what is still needed, never more than once per
    piece per tick. Returns (actions, the next `swaps` dict).
    """
    if not swaps:
        return [], dict(swaps)
    live_status = {a["id"]: a.get("status") for a in live_agents}
    names = {a["id"]: a.get("name", a["id"]) for a in live_agents}
    by_id = {i["id"]: i for i in issues}
    actions = []
    remaining = dict(swaps)

    for lead_key, swap in swaps.items():
        returning = swap.get("phase") == "returning"
        try:
            started_ts = parse_ts(swap["startedAt"])
        except (KeyError, TypeError, ValueError):
            warnings.append(f"swap for {lead_key!r} has a bad or missing startedAt; clearing it")
            del remaining[lead_key]
            continue
        if not returning and now - started_ts < SWAP_BACK_AFTER:
            continue

        lead_id, twin_id = swap.get("leadId"), swap.get("twinId")
        twin_key = swap.get("twinKey", lead_key)
        lead_name, twin_name = names.get(lead_id, lead_key), names.get(twin_id, twin_key)

        cap_reason = capped_aids.get(lead_id)
        if cap_reason and not returning:
            warnings.append(f"swap-back for {lead_key!r} held: {lead_name} is still capped ({cap_reason})")
            continue

        if not returning:
            swap = dict(swap, phase="returning")
            remaining[lead_key] = swap

        lead_resumed = live_status.get(lead_id) != "paused"
        twin_paused = live_status.get(twin_id) == "paused"
        still_on_twin = [
            by_id[iid] for iid in swap.get("issueIds", [])
            if iid in by_id and by_id[iid].get("assigneeAgentId") == twin_id
            and by_id[iid].get("status") in GATED
        ]

        if not lead_resumed:
            actions.append(Action("POST", f"/api/agents/{lead_id}/resume", None,
                                  f"resume {lead_name}: swap window over"))
        if not twin_paused:
            actions.append(Action("POST", f"/api/agents/{twin_id}/pause", None,
                                  f"pause {twin_name}: swap window over"))
        for issue in still_on_twin:
            iid = issue["id"]
            name = issue.get("identifier") or iid
            actions.append(Action("PATCH", f"/api/issues/{iid}", {
                "assigneeAgentId": lead_id,
                "comment": f"Watchdog: the swap window ended. Moved back to {lead_name} from {twin_name}.",
            }, f"reassign {name} back to {lead_name}", ref=f"swapback:{lead_key}:{iid}"))

        if lead_resumed and twin_paused and not still_on_twin:
            del remaining[lead_key]
    return actions, remaining


def decide(cfg, runs, issues, live_agents, seen, label_id, now, activity=None,
           interactions=None, documents=None, wiki_request_label_id=None, swaps=None):
    warnings = []
    actions = _pauses(cfg, runs, live_agents, now, warnings)
    breaker = _run_cap_breaker_pauses(cfg, runs, live_agents, now, warnings)
    already = {a.path for a in actions}
    actions += [a for a in breaker if a.path not in already]
    capped_aids = _capped_now(cfg, runs, live_agents, now)
    worker = _worker_pauses(cfg, issues, live_agents, seen, warnings)
    already = {a.path for a in actions}
    actions += [a for a in worker if a.path not in already]
    origin_runs = {r["id"]: r for r in runs if r.get("id")}
    gated = _gate(cfg, issues, activity or {}, live_agents, wiki_request_label_id, origin_runs)
    already = {a.path for a in actions}
    actions += [a for a in gated if a.path not in already]
    parked, judged = _park(cfg, issues, live_agents, seen, label_id, wiki_request_label_id, origin_runs)
    # One PATCH per issue. An issue both gated and parked is parked, because
    # backlog with no assignee also holds the gate, and it keeps the gate's note.
    gate_notes = {a.ref: a.body["comment"] for a in actions if a.ref and a.method == "PATCH"}
    for a in parked:
        if a.ref in gate_notes:
            a.body = {**a.body, "comment": gate_notes[a.ref]}
    parked_refs = {a.ref for a in parked}
    actions = [a for a in actions if not (a.method == "PATCH" and a.ref in parked_refs)]
    # An issue parked this pass is not started, even if a card on it was accepted.
    approved = _approvals(cfg, [i for i in issues if i["id"] not in parked_refs],
                          interactions or {}, documents or {}, seen, live_agents, warnings)
    swaps = _validated_swaps(cfg, dict(swaps or {}), agent_ids(cfg, live_agents), warnings)
    due = _due_swap_keys(swaps, now)
    swap_out, swaps = _swap_out(cfg, runs, issues, live_agents, swaps, now, warnings, due_keys=due)
    swap_back, swaps = _swap_back(cfg, live_agents, issues, swaps, now, warnings, capped_aids)
    return Decision(actions + parked + approved + swap_out + swap_back,
                    set(seen) | judged | {a.ref for a in approved}, warnings, swaps)


def execute(decision, client, dry_run, stamp):
    """Send each action on its own. A failed park leaves its issue unjudged, so
    the next pass tries it again. Returns (lines, seen, failed)."""
    lines = [f"{stamp} warning: {w}" for w in decision.warnings]
    seen = set(decision.seen)
    failed = 0
    for action in decision.actions:
        if dry_run:
            lines.append(f"{stamp} plan: {action.summary}")
            continue
        try:
            client.send(action.method, action.path, action.body)
            lines.append(f"{stamp} done: {action.summary}")
        except PaperclipError as err:
            failed += 1
            lines.append(f"{stamp} failed: {action.summary}: {err}")
            if action.ref:
                seen.discard(action.ref)
    return lines, seen, failed


def _fetch_each(client, issue_ids, what, lines, stamp):
    """One GET per issue. A failed issue is skipped with a warning, so one bad
    issue does not stop the pauses and the gate for every other issue."""
    out = {}
    for iid in issue_ids:
        try:
            out[iid] = client.get(f"/api/issues/{iid}/{what}")
        except PaperclipError as err:
            lines.append(f"{stamp} warning: could not read {what} of issue {iid}: {err}")
    return out


def _load_state(path):
    """Seen issue ids and active swaps. A missing or unreadable file means both
    start empty: those issues are judged again, which changes nothing for a
    filing already parked, and no swap is assumed active, which is only wrong
    for the moment it takes a fresh run of `_swap_out` to notice a lead's two
    newest runs are still both failed and swap it right back in."""
    try:
        raw = json.loads(Path(path).read_text())
        return set(raw.get("seenIssueIds", [])), raw.get("swaps", {}), None
    except FileNotFoundError:
        return set(), {}, None
    except (ValueError, AttributeError) as err:
        return set(), {}, f"state file unreadable, starting empty: {err}"


def _save_state(path, seen, swaps):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"seenIssueIds": sorted(seen), "swaps": swaps}, indent=1) + "\n")
    os.replace(tmp, path)


def _load_seen(path):
    """Back-compat wrapper over `_load_state` for a caller that only wants the
    seen set."""
    seen, _swaps, warning = _load_state(path)
    return seen, warning


def _save_seen(path, seen):
    """Back-compat wrapper over `_save_state` that preserves whatever swaps the
    file already held, since a caller with only a seen set to write has no swaps
    of its own to report."""
    _, swaps, _ = _load_state(path)
    _save_state(path, seen, swaps)


def _log(log_path, lines):
    if not lines:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as log:
        log.write("\n".join(lines) + "\n")


def state_path(cfg, flag):
    """The seen-issues file: `--state` if given, else the config's
    `watchdog.stateFile`, so a second company keeps its own."""
    if flag:
        return Path(flag)
    return REPO_ROOT / cfg.get("watchdog", {}).get("stateFile", ".paperclip/watchdog-state.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="company.json, or an overlay such as paperclip/orgs/<name>.json")
    parser.add_argument("--state", default=None,
                        help="state file (seen issues and active swaps); default is the config's "
                             "watchdog.stateFile")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    log_path = REPO_ROOT / ".paperclip" / "watchdog.log"
    lines = []
    try:
        cfg = load_config(args.config)
        cid = cfg["companyId"]
        log_path = REPO_ROOT / cfg.get("watchdog", {}).get("logFile", ".paperclip/watchdog.log")
        client = Client(cfg["apiBase"])
        labels = {lb["name"]: lb["id"] for lb in client.get(f"/api/companies/{cid}/labels")}
        if SCOPE_CREEP not in labels:
            raise PaperclipError("no scope-creep label; run scripts/paperclip-apply.py --apply first")
        state = state_path(cfg, args.state)
        seen, swaps, state_warning = _load_state(state)
        if state_warning:
            lines.append(f"{stamp} warning: {state_warning}")
        board = cfg.get("watchdog", {}).get("boardUserId", "local-board")
        issues = attach_policies(client, client.get(f"/api/companies/{cid}/issues"), board, lines, stamp)
        activity = _fetch_each(client, [i["id"] for i in gate_candidates(issues)], "activity", lines, stamp)
        interactions = _fetch_each(client, [i["id"] for i in approval_candidates(issues, board)],
                                   "interactions", lines, stamp)
        documents = _fetch_each(client, [
            iid for iid, cards in interactions.items()
            if any(((c.get("result") or {}).get("outcome") or c.get("status")) == "accepted"
                   for c in _scope_cards(cards))
        ], "documents", lines, stamp)
        decision = decide(
            cfg,
            client.get(f"/api/companies/{cid}/heartbeat-runs"),
            issues,
            client.get(f"/api/companies/{cid}/agents"),
            seen,
            labels[SCOPE_CREEP],
            now,
            activity,
            interactions,
            documents,
            labels.get(WIKI_REQUEST_LABEL),
            swaps,
        )
        done, seen, failed = execute(decision, client, args.dry_run, stamp)
        lines.extend(done)
        if not args.dry_run:
            _save_state(state, seen, decision.swaps)
        code = 1 if failed else 0
    except Exception as err:  # noqa: BLE001 - the only brake must say why it stopped
        lines.append(f"{stamp} error: {type(err).__name__}: {err}")
        code = 1

    for line in lines:
        print(line, file=sys.stderr if " error: " in line or " failed: " in line else sys.stdout)
    if not args.dry_run:
        _log(log_path, lines)
    return code


if __name__ == "__main__":
    sys.exit(main())
