#!/usr/bin/env python3
"""Set up this workbench on a new Mac, or check one. Run it as `./bootstrap.sh`.

Each step checks one thing. A step this script can fix safely, it fixes; a
step that needs a person, such as a sign-in or an interactive installer,
prints the exact commands and waits for the next run. Run it again after each
manual step until nothing is left. Every step is safe to run twice.

    ./bootstrap.sh              # check each step and fix what it can
    ./bootstrap.sh --check      # check only; change nothing
    ./bootstrap.sh --json       # the same report as JSON, for an agent
    ./bootstrap.sh --only node,repos

Every value particular to one practice comes from `bootstrap.settings.json` at
the workbench root, never from this file. A setting still holding an
angle-bracket placeholder, or an empty list, makes its step `skipped`: the
step names the setting to fill and judges nothing. A `skipped` step blocks
nothing and leaves the exit code alone.

Standard library only, so it runs on the `/usr/bin/python3` a new Mac ships.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
SETTINGS_NAME = "bootstrap.settings.json"
SETTINGS_FILE = REPO / SETTINGS_NAME
API = "http://127.0.0.1:3100"
NEW_ORG = "paperclip-new-org.py"
# The reverse-DNS prefix every launchd label here is built from. A prefix names
# a practice, so it is a setting; an unset or placeholder value leaves the
# watchdog step `skipped` rather than writing a label built from a placeholder.
LABEL_PREFIX = "launchd_label_prefix"
PLACEHOLDER = re.compile(r"<[^<>]*>")
PASSING = ("ok", "fixed", "skipped")


# --- settings -----------------------------------------------------------------

def has_placeholder(value):
    """Whether any string inside `value` still holds an angle-bracket placeholder."""
    if isinstance(value, str):
        return bool(PLACEHOLDER.search(value))
    if isinstance(value, dict):
        return any(has_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(has_placeholder(v) for v in value)
    return False


def placeholder_keys(value, prefix=""):
    """Every dotted key under `value` whose string still holds a placeholder."""
    found = []
    if isinstance(value, dict):
        for key, sub in value.items():
            found += placeholder_keys(sub, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            found += placeholder_keys(sub, f"{prefix}[{index}]")
    elif isinstance(value, str) and PLACEHOLDER.search(value):
        found.append(prefix)
    return found


class Settings:
    """`bootstrap.settings.json`, read once. A missing file is a reason, never a raise."""

    def __init__(self, data=None, error=""):
        self.data = data or {}
        self.error = error

    @classmethod
    def load(cls, path=None):
        path = Path(path or SETTINGS_FILE)
        try:
            return cls(json.loads(path.read_text()))
        except FileNotFoundError:
            return cls({}, f"{SETTINGS_NAME} does not exist at the workbench root")
        except (OSError, ValueError) as err:
            return cls({}, f"{SETTINGS_NAME} cannot be read: {err}")

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def unconfigured(self, dotted):
        """Why this setting cannot be used yet, or None when it can."""
        if self.error:
            return self.error
        value = self.get(dotted, None)
        if value is None:
            return f"{dotted} is not set in {SETTINGS_NAME}"
        if isinstance(value, (list, dict, str)) and not value:
            return f"{dotted} is empty in {SETTINGS_NAME}"
        if has_placeholder(value):
            return f"{dotted} still holds a placeholder in {SETTINGS_NAME}"
        return None

    def first_unconfigured(self, *dotted):
        for key in dotted:
            reason = self.unconfigured(key)
            if reason:
                return reason
        return None

    def placeholders(self):
        return placeholder_keys(self.data)


# --- plumbing -----------------------------------------------------------------

class Runner:
    """The only thing that touches the machine. Tests replace it."""

    def run(self, cmd, cwd=None):
        try:
            p = subprocess.run([str(a) for a in cmd], cwd=cwd, capture_output=True,
                               text=True, timeout=900)
        except FileNotFoundError:
            return 127, ""
        except subprocess.TimeoutExpired:
            return 124, "timed out after 900 seconds"
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def which(self, name):
        return shutil.which(name) is not None

    def exists(self, path):
        return Path(path).exists()

    def get_json(self, url):
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())


@dataclass
class Context:
    repo: Path
    home: Path
    runner: Runner
    fix: bool
    settings: Settings = field(default_factory=Settings)

    @property
    def api(self):
        return self.settings.get("paperclip.api", API) or API


@dataclass
class Cmd:
    argv: list
    cwd: Path | None = None
    allow_fail: bool = False

    def show(self):
        text = shlex.join(str(a) for a in self.argv)
        return f"cd {shlex.quote(str(self.cwd))} && {text}" if self.cwd else text


@dataclass
class Write:
    path: Path
    text: str

    def show(self):
        return f"write {self.path}"


@dataclass
class Outcome:
    ok: bool
    detail: str = ""
    fix: list = field(default_factory=list)      # Cmd or Write, run in order
    manual: list = field(default_factory=list)   # commands or steps for a person
    skip: bool = False                           # a setting is not filled in yet


@dataclass
class Result:
    id: str
    title: str
    status: str             # ok, fixed, fixable, manual, blocked, failed, skipped
    detail: str = ""
    commands: list = field(default_factory=list)


@dataclass
class Step:
    id: str
    title: str
    check: object
    needs: tuple = ()


def skipped(reason):
    """A step that judges nothing, because a setting is not filled in yet."""
    return Outcome(False, reason, skip=True)


def at_least(text, minimum):
    """Whether the first dotted version in `text` is at least `minimum`."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return False
    return tuple(int(x) for x in m.groups()) >= tuple(int(x) for x in minimum.split("."))


def resolve_path(raw, ctx):
    """A settings path: under the home directory for `~`, absolute for `/`, else the workbench."""
    text = str(raw)
    if text.startswith("~"):
        return ctx.home / text[1:].lstrip("/")
    if text.startswith("/"):
        return Path(text)
    return ctx.repo / text


def substitute(args, name):
    """`{name}` in an argument list, replaced with a marketplace or pack name."""
    return [str(a).replace("{name}", name) for a in args]


def render_template(path, repo, original):
    """A tracked plist template with this checkout's path in place of `original`."""
    return Path(path).read_text().replace(str(original), str(repo))


def _module(name, file):
    """A sibling script by path; a hyphenated filename cannot be imported by name."""
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _launch_agent(ctx, label, text):
    plist = ctx.home / "Library" / "LaunchAgents" / f"{label}.plist"
    return [Write(plist, text), Cmd(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)])]


def live_configs(ctx):
    """The configs, `company.json` and each overlay, whose company is live."""
    load_config = _module("paperclip_lib", "paperclip_lib.py").load_config
    ids = {c.get("id") for c in (ctx.runner.get_json(f"{ctx.api}/api/companies") or [])}
    configs = [ctx.repo / "paperclip" / "company.json"] + sorted((ctx.repo / "paperclip" / "orgs").glob("*.json"))
    return [p for p in configs if p.exists() and load_config(p).get("companyId") in ids]


def _paperclip_off(ctx):
    """Why the Paperclip steps do not apply here, or None."""
    if ctx.settings.error:
        return ctx.settings.error
    if not ctx.settings.get("paperclip.enabled"):
        return f"paperclip.enabled is false in {SETTINGS_NAME}"
    return None


def _no_paperclip_dir(ctx):
    if not (ctx.repo / "paperclip").is_dir():
        return "paperclip/ does not exist in this workbench, so there is no company to run"
    return None


# --- the steps ----------------------------------------------------------------

def check_xcode(ctx):
    rc, _ = ctx.runner.run(["xcode-select", "-p"])
    return Outcome(rc == 0, "Command Line Tools installed" if rc == 0 else "Command Line Tools missing",
                   manual=["xcode-select --install"])


def check_homebrew(ctx):
    ok = ctx.runner.which("brew")
    return Outcome(ok, "brew found" if ok else "Homebrew missing",
                   manual=["Install Homebrew with the command at https://brew.sh, then open a new terminal"])


def check_brew_packages(ctx):
    reason = ctx.settings.unconfigured("brew_packages")
    if reason:
        return skipped(reason)
    packages = [str(p) for p in ctx.settings.get("brew_packages")]
    _, out = ctx.runner.run(["brew", "list", "--versions", *packages])
    have = {line.split()[0] for line in out.splitlines() if line.strip()}
    missing = [p for p in packages if p not in have]
    return Outcome(not missing, f"missing {', '.join(missing)}" if missing else ", ".join(packages),
                   fix=[Cmd(["brew", "install", *missing])])


def check_node(ctx):
    reason = ctx.settings.unconfigured("node_min")
    if reason:
        return skipped(reason)
    minimum = str(ctx.settings.get("node_min"))
    rc, out = ctx.runner.run(["node", "--version"])
    ok = rc == 0 and at_least(out, minimum)
    return Outcome(ok, out.strip() or "node missing", manual=[
        "Install nvm from https://github.com/nvm-sh/nvm",
        f"nvm install {minimum} && nvm alias default {minimum}",
        "Open a new terminal"])


def check_agent_cli(ctx):
    reason = ctx.settings.first_unconfigured("agent_cli.command", "agent_cli.min_version",
                                             "agent_cli.version_args")
    if reason:
        return skipped(reason)
    cli = ctx.settings.get("agent_cli")
    command = str(cli["command"])
    minimum = str(cli["min_version"])
    rc, out = ctx.runner.run([command, *cli["version_args"]])
    if rc == 127:
        note = cli.get("sign_in_note") or ""
        return Outcome(False, f"{command} is not on the PATH",
                       manual=[f"Install {command}"] + ([note] if note else []))
    ok = at_least(out, minimum)
    return Outcome(ok, out.strip() if ok else f"{out.strip()}; {minimum} or newer is wanted",
                   fix=[Cmd([command, *cli.get("update_args", [])])] if cli.get("update_args") else [])


def check_gh_auth(ctx):
    rc, _ = ctx.runner.run(["gh", "auth", "status"])
    return Outcome(rc == 0, "signed in" if rc == 0 else "gh is not signed in",
                   manual=["gh auth login", "gh auth refresh -s project"])


def check_git_hooks(ctx):
    _, out = ctx.runner.run(["git", "config", "--get", "core.hooksPath"], cwd=ctx.repo)
    ok = out.strip() == ".githooks"
    return Outcome(ok, ".githooks" if ok else "hooks not enabled in this clone",
                   fix=[Cmd(["git", "config", "core.hooksPath", ".githooks"], cwd=ctx.repo)])


def check_repos(ctx):
    reason = ctx.settings.unconfigured("repos")
    if reason:
        return skipped(reason)
    targets = [(resolve_path(r["path"], ctx), str(r["remote"])) for r in ctx.settings.get("repos")]
    missing = [(path, remote) for path, remote in targets if not ctx.runner.exists(path)]
    return Outcome(not missing, f"{len(missing)} missing" if missing else "all cloned",
                   fix=[Cmd(["gh", "repo", "clone", remote, str(path)]) for path, remote in missing])


def check_packs(ctx):
    reason = ctx.settings.first_unconfigured("agent_cli.command", "packs.list_args",
                                             "packs.install_args", "packs.install")
    if reason:
        return skipped(reason)
    command = str(ctx.settings.get("agent_cli.command"))
    packs = ctx.settings.get("packs")
    _, out = ctx.runner.run([command, *packs["list_args"]])
    missing = [p for p in packs["install"] if p not in out]
    fix = [Cmd([command, *substitute(packs.get("marketplace_add_args", []), m)], allow_fail=True)
           for m in packs.get("marketplaces", []) if packs.get("marketplace_add_args")]
    fix += [Cmd([command, *substitute(packs["install_args"], p)]) for p in missing]
    return Outcome(not missing, f"missing {', '.join(missing)}" if missing else "every pack installed",
                   fix=fix)


def check_cli_tools(ctx):
    reason = ctx.settings.unconfigured("cli_tools")
    if reason:
        return skipped(reason)
    fix, missing = [], []
    for tool in ctx.settings.get("cli_tools"):
        name = str(tool.get("name", ""))
        if ctx.runner.which(name):
            continue
        missing.append(name)
        fix.append(Cmd(list(tool.get("install", []))))
        fix += [Cmd(list(after)) for after in tool.get("after") or []]
    return Outcome(not missing, f"missing {', '.join(missing)}" if missing else "every tool found",
                   fix=fix)


def check_paperclip_cli(ctx):
    reason = _paperclip_off(ctx) or ctx.settings.unconfigured("paperclip.version")
    if reason:
        return skipped(reason)
    want = str(ctx.settings.get("paperclip.version"))
    rc, out = ctx.runner.run(["paperclipai", "--version"])
    if rc == 0:
        detail = out.strip() if want in out else f"{out.strip()}; this workbench was tested on {want}"
        return Outcome(True, detail)
    return Outcome(False, "paperclipai missing", fix=[Cmd(["npm", "install", "-g", f"paperclipai@{want}"])])


def check_paperclip_server(ctx):
    reason = _paperclip_off(ctx)
    if reason:
        return skipped(reason)
    try:
        ctx.runner.get_json(f"{ctx.api}/api/companies")
        return Outcome(True, f"answering at {ctx.api}")
    except (OSError, ValueError):
        return Outcome(False, f"no server at {ctx.api}. Onboarding asks questions: pick loopback, or "
                              "a private network to reach it from a phone", manual=[
                                  "paperclipai onboard", "paperclipai service install",
                                  "paperclipai service status"])


def check_paperclip_company(ctx):
    reason = _paperclip_off(ctx) or _no_paperclip_dir(ctx)
    if reason:
        return skipped(reason)
    live = live_configs(ctx)
    if live:
        return Outcome(True, "live: " + ", ".join(str(p.relative_to(ctx.repo)) for p in live))
    return Outcome(False, "no company in paperclip/ is live on this server", manual=[
        "cp paperclip/company.json paperclip/orgs/<machine>.json",
        "In the copy, set companyId to null, set company.name, and delete each agentOverrides id",
        f"python3 scripts/{NEW_ORG} paperclip/orgs/<machine>.json --apply",
        "Commit paperclip/orgs/<machine>.json on a branch and open a pull request"])


def check_watchdog(ctx):
    reason = (_paperclip_off(ctx) or _no_paperclip_dir(ctx)
              or ctx.settings.unconfigured(LABEL_PREFIX))
    if reason:
        return skipped(reason)
    sibling = SCRIPTS / NEW_ORG
    if not sibling.exists():
        return skipped(f"scripts/{NEW_ORG} does not exist yet, and it names and writes each watchdog agent")
    live = live_configs(ctx)
    if not live:
        return skipped("no company in paperclip/ is live on this server, so there is no watchdog to load")
    org = _module("paperclip_new_org", NEW_ORG)
    prefix = str(ctx.settings.get(LABEL_PREFIX))
    _, loaded = ctx.runner.run(["launchctl", "list"])
    fix, missing = [], []
    for config in live:
        label = org.watchdog_label(config, prefix=prefix)
        if label in loaded:
            continue
        missing.append(label)
        fix += _launch_agent(ctx, label, org.watchdog_plist(config, repo=ctx.repo, prefix=prefix))
    return Outcome(not missing, f"missing {', '.join(missing)}" if missing else "a watchdog runs for each live company",
                   fix=fix)


def check_launch_agents(ctx):
    reason = ctx.settings.first_unconfigured("launch_agents", "workbench_path_in_templates")
    if reason:
        return skipped(reason)
    original = str(ctx.settings.get("workbench_path_in_templates"))
    entries = [(str(a["label"]), resolve_path(a["template"], ctx)) for a in ctx.settings.get("launch_agents")]
    absent = [str(path) for _, path in entries if not path.is_file()]
    if absent:
        return skipped("no template on disk at " + ", ".join(absent))
    _, loaded = ctx.runner.run(["launchctl", "list"])
    fix, missing = [], []
    for label, template in entries:
        if label in loaded:
            continue
        missing.append(label)
        fix += _launch_agent(ctx, label, render_template(template, ctx.repo, original))
    return Outcome(not missing, f"missing {', '.join(missing)}" if missing else "every agent loaded",
                   fix=fix)


def check_review_webhook(ctx):
    reason = ctx.settings.first_unconfigured("review_webhook.path", "review_webhook.how")
    if reason:
        return skipped(reason)
    path = resolve_path(ctx.settings.get("review_webhook.path"), ctx)
    ok = ctx.runner.exists(path)
    return Outcome(ok, f"{path} present" if ok else f"{path} is absent, so no review can post to chat",
                   manual=[str(h) for h in ctx.settings.get("review_webhook.how")])


def check_always_on(ctx):
    _, out = ctx.runner.run(["pmset", "-g"])
    m = re.search(r"^\s*sleep\s+(\d+)", out, re.MULTILINE)
    ok = bool(m) and m.group(1) == "0"
    return Outcome(ok, "system sleep off" if ok else "the Mac sleeps, which stops every agent run", manual=[
        "sudo pmset -c sleep 0"])


STEPS = [
    Step("xcode-clt", "Xcode Command Line Tools", check_xcode),
    Step("homebrew", "Homebrew", check_homebrew, ("xcode-clt",)),
    Step("brew-packages", "The Homebrew packages in settings", check_brew_packages, ("homebrew",)),
    Step("node", "Node, at the minimum in settings", check_node),
    Step("agent-cli", "The agent command line in settings", check_agent_cli),
    Step("gh-auth", "GitHub CLI sign-in", check_gh_auth, ("brew-packages",)),
    Step("git-hooks", "Git hooks for this clone", check_git_hooks),
    Step("repos", "The repositories in settings", check_repos, ("gh-auth",)),
    Step("packs", "The packs in settings", check_packs, ("agent-cli",)),
    Step("cli-tools", "The command-line tools in settings", check_cli_tools, ("node",)),
    Step("paperclip-cli", "The Paperclip CLI", check_paperclip_cli, ("node",)),
    Step("paperclip-server", "Paperclip server", check_paperclip_server, ("paperclip-cli",)),
    Step("paperclip-company", "A Paperclip company from paperclip/", check_paperclip_company,
         ("paperclip-server",)),
    Step("watchdog", "A Paperclip watchdog per company", check_watchdog, ("paperclip-company",)),
    Step("launch-agents", "The launchd agents in settings", check_launch_agents),
    Step("review-webhook", "The review chat webhook", check_review_webhook),
    Step("always-on", "No system sleep on power", check_always_on),
]


# --- running and reporting ------------------------------------------------------

def _apply(ctx, actions):
    """Run each fix action in order. Returns an error text, or None."""
    for action in actions:
        if isinstance(action, Write):
            action.path.parent.mkdir(parents=True, exist_ok=True)
            action.path.write_text(action.text)
            continue
        rc, out = ctx.runner.run(action.argv, cwd=action.cwd)
        if rc != 0 and not action.allow_fail:
            return f"`{action.show()}` failed ({rc}): {out.strip()[:300]}"
    return None


def _check(step, ctx):
    try:
        return step.check(ctx), None
    except Exception as err:  # noqa: BLE001 - one broken check must not hide the rest
        return None, f"check raised {type(err).__name__}: {err}"


def _run_one(step, ctx):
    outcome, error = _check(step, ctx)
    if error:
        return Result(step.id, step.title, "failed", error)
    if outcome.skip:
        return Result(step.id, step.title, "skipped", outcome.detail)
    if outcome.ok:
        return Result(step.id, step.title, "ok", outcome.detail)
    if not outcome.fix:
        return Result(step.id, step.title, "manual", outcome.detail, list(outcome.manual))
    shown = [a.show() for a in outcome.fix]
    if not ctx.fix:
        return Result(step.id, step.title, "fixable", outcome.detail, shown)
    error = _apply(ctx, outcome.fix)
    if error:
        return Result(step.id, step.title, "failed", error, shown)
    again, error = _check(step, ctx)
    if error:
        return Result(step.id, step.title, "failed", error, shown)
    if again.skip:
        return Result(step.id, step.title, "skipped", again.detail)
    if again.ok:
        return Result(step.id, step.title, "fixed", again.detail)
    return Result(step.id, step.title, "failed", f"the fix ran, but: {again.detail}", shown + list(again.manual))


def run_steps(ctx, only=None):
    """Each step in order. A step whose prerequisite did not pass is `blocked`.
    A prerequisite left out by `only`, or skipped, is not judged."""
    results, status = [], {}
    for step in STEPS:
        if only and step.id not in only:
            continue
        waiting = [n for n in step.needs if n in status and status[n] not in PASSING]
        r = Result(step.id, step.title, "blocked", "waits for " + ", ".join(waiting)) if waiting else _run_one(step, ctx)
        status[step.id] = r.status
        results.append(r)
    return results


def exit_code(results):
    return 0 if all(r.status in PASSING for r in results) else 1


def _placeholder_line(placeholders):
    if placeholders:
        return f"Still to fill in, in {SETTINGS_NAME}: " + ", ".join(placeholders)
    return f"Nothing is left to fill in, in {SETTINGS_NAME}."


def report_json(results, placeholders=()):
    summary = dict(collections.Counter(r.status for r in results))
    return json.dumps({"summary": summary, "placeholders": list(placeholders),
                       "steps": [asdict(r) for r in results]}, indent=2)


def report_text(results, placeholders=()):
    lines = [f"[{r.status:7}] {r.title}: {r.detail}" for r in results]
    todo = [r for r in results if r.status in ("manual", "fixable", "failed")]
    lines.append("")
    if todo:
        lines.append("Next steps:")
        for n, r in enumerate(todo, 1):
            lines.append(f"{n}. {r.title}")
            lines.extend(f"     {c}" for c in r.commands)
        lines.append("")
        if any(r.status in ("manual", "failed") for r in todo):
            lines.append("Do these, then rerun ./bootstrap.sh")
        else:
            lines.append("Run ./bootstrap.sh without --check to fix these, then rerun ./bootstrap.sh")
    elif any(r.status == "blocked" for r in results):
        lines.append("Some steps wait on others; rerun ./bootstrap.sh")
    else:
        lines.append("Nothing left to do.")
    lines.append("")
    lines.append(_placeholder_line(list(placeholders)))
    return "\n".join(lines)


def main(argv=None, ctx=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check only; change nothing")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--only", help="comma-separated step ids: " + ", ".join(s.id for s in STEPS))
    args = parser.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None
    unknown = (only or set()) - {s.id for s in STEPS}
    if unknown:
        parser.error(f"unknown step: {', '.join(sorted(unknown))}")
    if ctx is None:
        ctx = Context(repo=REPO, home=Path.home(), runner=Runner(), fix=not args.check,
                      settings=Settings.load())
    else:
        ctx.fix = not args.check
    placeholders = ctx.settings.placeholders()
    results = run_steps(ctx, only)
    print(report_json(results, placeholders) if args.json else report_text(results, placeholders))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
