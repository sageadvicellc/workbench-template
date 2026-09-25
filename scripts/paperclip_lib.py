"""Shared helpers for the Paperclip scripts: config loading and a tiny client.

Standard library only. The server runs in `local_trusted` mode on loopback, so
no key is needed there. If `PAPERCLIP_BOARD_API_KEY` is set, it is sent as a
bearer token, which is what a caller off this machine needs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "paperclip" / "company.json"


@dataclass
class Action:
    method: str
    path: str
    body: dict | None
    summary: str = field(default="")
    ref: str | None = None


def load_config(path=DEFAULT_CONFIG):
    return json.loads(Path(path).read_text())


class PaperclipError(RuntimeError):
    pass


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
                raise PaperclipError(f"{len(matches)} live agents are named {agent['name']!r}; set its id in company.json")
            out[agent["key"]] = matches[0]
    return out
