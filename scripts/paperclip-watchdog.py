#!/usr/bin/env python3
"""The only automated stop on the Paperclip team. No model is called.

A fleet that bills through a subscription reports every run as
`subscription_included` with no cost, so Paperclip's dollar budgets never
fire. This script is the brake that works on any billing. Each pass it:

1. Pauses an agent that reached its `runsPerDay` cap for the current UTC day.
2. Pauses every agent after a burst of `OAuth session expired` failures in the
   last 15 minutes, so a dead login does not strand a queue of runs.
3. Holds the approval gate. If an agent assigned an open issue to an agent,
   the issue goes back to the board in `in_review` and the assigning agent is
   paused. Paperclip lets every active agent assign tasks, whatever its
   `canAssignTasks` flag says, so this check is the gate's only enforcement.
4. Parks work that no person asked for. The first time it sees an issue that
   no person created and no routine created, it moves the issue to
   `backlog`, clears the assignee, and adds the `scope-creep` label. An issue
   is judged once. If the owner later approves it, the watchdog leaves it alone.

    python3 scripts/paperclip-watchdog.py --dry-run   # print, change nothing
    python3 scripts/paperclip-watchdog.py             # act and log

Resume a paused agent from the Paperclip UI, or with
`POST /api/agents/{id}/resume`.
"""

import argparse
import json
import os
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
)

AUTH_WINDOW = timedelta(minutes=15)
CLOSED = {"done", "cancelled"}
GATED = {"todo", "in_progress", "blocked"}
SCOPE_CREEP = "scope-creep"


@dataclass
class Decision:
    actions: list = field(default_factory=list)
    seen: set = field(default_factory=set)
    warnings: list = field(default_factory=list)


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
        if aid is None or not cap:
            continue
        count = 0
        for r in runs:
            if r.get("agentId") != aid:
                continue
            ts = _ts(r)
            if ts is None or ts.date() == today:
                count += 1
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


def _park(issues, seen, label_id):
    actions, judged = [], set()
    for issue in issues:
        iid = issue["id"]
        if iid in seen or issue.get("createdByUserId") or issue.get("originKind") == "routine_execution":
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


def _gate(cfg, issues, activity, live_agents):
    """Send back each open issue whose current agent assignment an agent made.

    `activity` maps an issue id to its events, newest first, as
    `GET /api/issues/{id}/activity` returns them.
    """
    board = cfg.get("watchdog", {}).get("boardUserId", "local-board")
    names = {a["id"]: a.get("name", a["id"]) for a in live_agents}
    status = {a["id"]: a.get("status") for a in live_agents}
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


def decide(cfg, runs, issues, live_agents, seen, label_id, now, activity=None):
    warnings = []
    actions = _pauses(cfg, runs, live_agents, now, warnings)
    gated = _gate(cfg, issues, activity or {}, live_agents)
    already = {a.path for a in actions}
    actions += [a for a in gated if a.path not in already]
    parked, judged = _park(issues, seen, label_id)
    # One PATCH per issue. An issue both gated and parked is parked, because
    # backlog with no assignee also holds the gate, and it keeps the gate's note.
    gate_notes = {a.ref: a.body["comment"] for a in actions if a.ref and a.method == "PATCH"}
    for a in parked:
        if a.ref in gate_notes:
            a.body = {**a.body, "comment": gate_notes[a.ref]}
    parked_refs = {a.ref for a in parked}
    actions = [a for a in actions if not (a.method == "PATCH" and a.ref in parked_refs)]
    return Decision(actions + parked, set(seen) | judged, warnings)


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


def _load_seen(path):
    """Seen issue ids. A missing or unreadable file means an empty set: those
    issues are judged again, which changes nothing for a filing already parked."""
    try:
        return set(json.loads(Path(path).read_text()).get("seenIssueIds", [])), None
    except FileNotFoundError:
        return set(), None
    except (ValueError, AttributeError) as err:
        return set(), f"state file unreadable, starting empty: {err}"


def _save_seen(path, seen):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"seenIssueIds": sorted(seen)}, indent=1) + "\n")
    os.replace(tmp, path)


def _log(log_path, lines):
    if not lines:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as log:
        log.write("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--state", default=str(REPO_ROOT / ".paperclip" / "watchdog-state.json"))
    parser.add_argument("--dry-run", action="store_true")
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
        seen, state_warning = _load_seen(args.state)
        if state_warning:
            lines.append(f"{stamp} warning: {state_warning}")
        issues = client.get(f"/api/companies/{cid}/issues")
        activity = {i["id"]: client.get(f"/api/issues/{i['id']}/activity") for i in gate_candidates(issues)}
        decision = decide(
            cfg,
            client.get(f"/api/companies/{cid}/heartbeat-runs"),
            issues,
            client.get(f"/api/companies/{cid}/agents"),
            seen,
            labels[SCOPE_CREEP],
            now,
            activity,
        )
        done, seen, failed = execute(decision, client, args.dry_run, stamp)
        lines.extend(done)
        if not args.dry_run:
            _save_seen(args.state, seen)
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
