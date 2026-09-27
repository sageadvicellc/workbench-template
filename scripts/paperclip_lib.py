"""Shared helpers for the Paperclip scripts: config loading and a tiny client.

Standard library only. The server runs in `local_trusted` mode on loopback, so
no key is needed there. If `PAPERCLIP_BOARD_API_KEY` is set, it is sent as a
bearer token, which is what a non-loopback caller needs.

Nothing in this file names a practice. The one value that would, the
reverse-DNS prefix every launchd label is built from, comes from
`bootstrap.settings.json` through `launchd_label_prefix` below.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "paperclip" / "company.json"
SETTINGS_NAME = "bootstrap.settings.json"
SETTINGS_FILE = REPO_ROOT / SETTINGS_NAME
LABEL_PREFIX_KEY = "launchd_label_prefix"
# The same angle-bracket convention `bootstrap.py` uses for an unconfigured
# setting. A value still holding one is not a value.
PLACEHOLDER = re.compile(r"<[^<>]*>")


@dataclass
class Action:
    method: str
    path: str
    body: dict | None
    summary: str = field(default="")
    ref: str | None = None


class PaperclipError(RuntimeError):
    pass


def load_config(path=DEFAULT_CONFIG):
    """Read a company config. An overlay names its base with `extends`.

    An overlay, such as `paperclip/orgs/<name>.json`, runs the same team as
    its base against another company. Its objects merge into the base's, key
    by key; any other value, a list included, replaces the base's. Its
    `agentOverrides` merges into each base agent by key. A base agent's `id`
    belongs to the base company, so an overlay for another company drops it,
    and each agent is matched by name until the overlay records its own id.

    An overlay's `extraAgents` is a list of whole agent entries, such as a
    standby twin, that exist only in this company and not in the base. Each
    entry is appended after the merged base agents, in file order. A key that
    collides with a base agent, or with another `extraAgents` entry, is a
    config error: `agentOverrides` is how an overlay changes a base agent, and
    a colliding key would make it ambiguous which one a later override or a run
    cap meant.
    """
    path = Path(path)
    cfg = json.loads(path.read_text())
    base_ref = cfg.pop("extends", None)
    if base_ref is None:
        return cfg
    base = load_config((path.parent / base_ref).resolve())
    overrides = cfg.pop("agentOverrides", {})
    extra_agents = cfg.pop("extraAgents", [])
    base_keys = {a["key"] for a in base.get("agents", [])}
    unknown = sorted(set(overrides) - base_keys)
    if unknown:
        raise PaperclipError(f"{path.name}: agentOverrides names no agent in {base_ref}: {unknown}")
    extra_keys = [a["key"] for a in extra_agents]
    dup_with_base = sorted(set(extra_keys) & base_keys)
    if dup_with_base:
        raise PaperclipError(f"{path.name}: extraAgents key(s) already in {base_ref}: {dup_with_base}")
    if len(extra_keys) != len(set(extra_keys)):
        raise PaperclipError(f"{path.name}: extraAgents has a duplicate key: {extra_keys}")
    merged = _merge(base, cfg)
    other_company = merged.get("companyId") != base.get("companyId")
    if "agents" not in cfg:
        agents = []
        for agent in base.get("agents", []):
            if other_company:
                agent = {k: v for k, v in agent.items() if k != "id"}
            agents.append(_merge(agent, overrides.get(agent["key"], {})))
        merged["agents"] = agents
    merged["agents"] = merged.get("agents", []) + list(extra_agents)
    return merged


def _merge(base, over):
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def launchd_label_prefix(settings_path=SETTINGS_FILE):
    """The reverse-DNS prefix every launchd label in this workbench is built
    from, read from `bootstrap.settings.json`.

    A label prefix names a practice, so it is a setting and never a literal in
    a script. Three scripts need it, which is why the one loader lives here. A
    missing file, an unset key, an empty string, or a value still holding an
    angle-bracket placeholder is a `PaperclipError` naming the key, never a
    traceback and never a label built from a placeholder. `bootstrap.py` asks
    its own `Settings` the same question and reports `skipped` instead.
    """
    path = Path(settings_path)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as err:
        raise PaperclipError(f"{SETTINGS_NAME} does not exist at {path}; "
                             f"set {LABEL_PREFIX_KEY} in it") from err
    except (OSError, ValueError) as err:
        raise PaperclipError(f"{SETTINGS_NAME} cannot be read: {err}") from err
    value = data.get(LABEL_PREFIX_KEY)
    if not isinstance(value, str) or not value.strip():
        raise PaperclipError(f"{LABEL_PREFIX_KEY} is not set in {SETTINGS_NAME}; "
                             'set it to a reverse-DNS prefix, such as "org.example.workbench"')
    value = value.strip()
    if PLACEHOLDER.search(value):
        raise PaperclipError(f"{LABEL_PREFIX_KEY} still holds a placeholder in {SETTINGS_NAME}: {value!r}")
    return value.rstrip(".")


def _positive_int(value, label):
    """A run cap is a positive whole number, or it is not a cap.

    A cap of `0` reads as "no cap configured" at every enforcement site in the
    watchdog, because each one guards on truthiness. Left alone it would
    disable the breaker instead of stopping the agent, silently and with no
    warning, so a `0` is refused here rather than obeyed there. A string, a
    float, or a negative fails the same way or worse. `bool` is an `int` in
    Python, hence the explicit exclusion.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PaperclipError(f"{label} must be a positive whole number, not {value!r}")
    if value <= 0:
        raise PaperclipError(f"{label} is {value}, which reads as no cap at all and enforces nothing; "
                             "write a positive whole number or leave the key out")


def validate_run_caps(cfg):
    """Every cap in `cfg` is a positive whole number, or this raises.

    Checks each agent's `runsPerDay` and, under `runCaps`, each adapter entry's
    `agents` caps and its `harnessTotal`. An absent cap is legal: it means
    uncapped on purpose. A cap written as `0` is not, for the reason in
    `_positive_int`.
    """
    for agent in cfg.get("agents") or []:
        if agent.get("runsPerDay") is not None:
            _positive_int(agent["runsPerDay"], f"agent {agent.get('key')!r} runsPerDay")
    for adapter, entry in (cfg.get("runCaps") or {}).items():
        if not isinstance(entry, dict):
            raise PaperclipError(f"runCaps[{adapter!r}] must be an object")
        for key, cap in (entry.get("agents") or {}).items():
            _positive_int(cap, f"runCaps[{adapter!r}] per-agent cap for {key!r}")
        if entry.get("harnessTotal") is not None:
            _positive_int(entry["harnessTotal"], f"runCaps[{adapter!r}].harnessTotal")


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class Client:
    def __init__(self, base, token=None, timeout=30):
        self.base = base.rstrip("/")
        self.token = token if token is not None else os.environ.get("PAPERCLIP_BOARD_API_KEY")
        self.timeout = timeout
        url = urllib.parse.urlparse(self.base)
        if self.token and url.scheme != "https" and url.hostname not in LOOPBACK:
            raise PaperclipError(f"refusing to send a bearer token over plain http to {url.hostname}")

    def _request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:300]
            raise PaperclipError(f"{method} {path} -> {err.code}: {detail}") from err
        except urllib.error.URLError as err:
            raise PaperclipError(f"{method} {path} -> {err.reason}") from err
        except OSError as err:
            raise PaperclipError(f"{method} {path} -> {err}") from err
        try:
            return json.loads(raw) if raw else None
        except ValueError as err:
            raise PaperclipError(f"{method} {path} -> response is not JSON: {raw[:120]!r}") from err

    def get(self, path):
        return self._request("GET", path)

    def send(self, method, path, body=None):
        return self._request(method, path, body)


def agent_ids(cfg, live_agents):
    """Map each configured agent key to its live id, by id first, then by name.

    A key with no live match is left out. Two live agents with one name is an
    error, because a name match could then push config onto the wrong agent.
    """
    by_name = {}
    for a in live_agents:
        by_name.setdefault(a["name"], []).append(a["id"])
    live = {a["id"] for a in live_agents}
    out = {}
    for agent in cfg["agents"]:
        if agent.get("id") in live:
            out[agent["key"]] = agent["id"]
        elif agent["name"] in by_name:
            matches = by_name[agent["name"]]
            if len(matches) > 1:
                raise PaperclipError(
                    f"{len(matches)} live agents are named {agent['name']!r}; set its id in company.json")
            out[agent["key"]] = matches[0]
    return out
