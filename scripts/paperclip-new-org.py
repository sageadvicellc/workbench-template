#!/usr/bin/env python3
"""Start a Paperclip company from an overlay under `paperclip/orgs/`.

An overlay extends `paperclip/company.json` and names the new company in
`company.name`. This script creates that company if the overlay has no
`companyId` yet, writes the new id back into the overlay, runs
`paperclip-apply.py` against it, and records each hired agent's id in the
overlay's `agentOverrides`. It changes nothing unless `--apply` is given.

    python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json            # dry run
    python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json --apply    # create and apply
    python3 scripts/paperclip-new-org.py paperclip/orgs/<name>.json --watchdog-plist

`--watchdog-plist` prints a launchd plist that runs the watchdog for this
company every five minutes. Its label is built from `launchd_label_prefix` in
`bootstrap.settings.json`; an unset or placeholder prefix is an error naming
that key, never a label built from a placeholder. Commit the overlay after
`--apply`, because the ids it records are how the next apply finds the same
agents.
"""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperclip_lib import (  # noqa: E402
    REPO_ROOT,
    Client,
    PaperclipError,
    agent_ids,
    launchd_label_prefix,
    load_config,
)

SCRIPTS = Path(__file__).resolve().parent
PLIST_TEMPLATE = SCRIPTS / "paperclip-watchdog.plist.template"
# The two substitution markers in that template, both settings keys. They use
# the same angle-bracket form `bootstrap.settings.json` ships its unset values
# in, so an unrendered file reads as unconfigured rather than as a real label.
LABEL_PREFIX_MARKER = "<reverse.dns.prefix>"
WORKBENCH_MARKER = "<absolute path of this workbench>"
WATCHDOG_SUFFIX = "paperclip-watchdog"


def _raw(path):
    raw = json.loads(Path(path).read_text())
    if "extends" not in raw:
        raise PaperclipError(f"{Path(path).name} has no `extends`; only an overlay under paperclip/orgs/ "
                             "can start a company")
    return raw


def _patch(path, change):
    """Apply `change` to a fresh read of the overlay and replace the file atomically.

    The read happens here, after any network call, so an edit made to the
    overlay while a request was in flight survives; only the keys `change` sets
    are written. A crash mid-write leaves the old file, not a torn one.
    """
    path = Path(path)
    raw = _raw(path)
    change(raw)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def ensure_company(path, client, apply):
    """Return (company id or None, report lines). Creates the company on --apply.

    A live company that already has the overlay's name is an error, not a match:
    a rerun after a lost write must not create a second one, and adopting a
    company by name alone could configure the wrong one.
    """
    raw = _raw(path)
    if raw.get("companyId"):
        return raw["companyId"], [f"company {raw['companyId']} is set in {Path(path).name}"]
    company = load_config(path).get("company", {})
    name = company.get("name")
    if not name:
        raise PaperclipError(f"{Path(path).name} names no company; set company.name")
    same = [c for c in (client.get("/api/companies") or []) if c.get("name") == name]
    if same:
        raise PaperclipError(f"a live company is already named {name!r} ({same[0]['id']}); "
                             f"set companyId to it in {Path(path).name} if it is this one")
    body = {"name": name}
    if company.get("description"):
        body["description"] = company["description"]
    if not apply:
        return None, [f"plan: create company {name!r}"]
    created = client.send("POST", "/api/companies", body) or {}
    if not created.get("id"):
        raise PaperclipError(f"company create returned no id: {created!r}")
    _patch(path, lambda fresh: fresh.__setitem__("companyId", created["id"]))
    return created["id"], [f"done: create company {name!r} (id {created['id']}, "
                           f"written to {Path(path).name})"]


def record_agent_ids(path, client):
    """Write each live agent's id into the overlay, by key.

    A key that names a base agent (matched through `agentOverrides`) is recorded
    there. A key that names one of the overlay's own `extraAgents`, such as a
    standby twin, is recorded on that entry directly instead: it has no base
    agent for `agentOverrides` to merge onto.
    """
    cfg = load_config(path)
    ids = agent_ids(cfg, client.get(f"/api/companies/{cfg['companyId']}/agents"))
    names = {a["key"]: a["name"] for a in cfg["agents"]}
    lines = []

    def record(fresh):
        overrides = fresh.setdefault("agentOverrides", {})
        extra_by_key = {a["key"]: a for a in fresh.get("extraAgents", [])}
        for key, aid in ids.items():
            if key in extra_by_key:
                if extra_by_key[key].get("id") != aid:
                    extra_by_key[key]["id"] = aid
                    lines.append(f"done: record {names[key]} as {aid}")
            elif overrides.get(key, {}).get("id") != aid:
                overrides.setdefault(key, {})["id"] = aid
                lines.append(f"done: record {names[key]} as {aid}")

    _patch(path, record)
    return lines


def watchdog_label(path, prefix=None):
    """The launchd label for this config's watchdog.

    The reverse-DNS prefix comes from `bootstrap.settings.json`, never from a
    literal here, because a label prefix names a practice. The config's file
    stem follows it, so every company on one machine gets its own label and its
    own launchd agent.
    """
    if prefix is None:
        prefix = launchd_label_prefix()
    return f"{prefix}.{WATCHDOG_SUFFIX}.{Path(path).stem}"


def watchdog_plist(path, python="/usr/bin/python3", repo=REPO_ROOT, prefix=None):
    """A launchd plist that runs the watchdog for this overlay every five minutes."""
    label = watchdog_label(path, prefix)
    config = Path(path).resolve()
    args = [python, str(Path(repo) / "scripts" / "paperclip-watchdog.py"), "--config", str(config)]
    strings = "\n".join(f"    <string>{escape(a)}</string>" for a in args)
    err_path = escape(str(Path(repo) / ".paperclip" / f"watchdog-{Path(path).stem}.err"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{escape(label)}</string>
  <key>ProgramArguments</key>
  <array>
{strings}
  </array>
  <key>StartInterval</key>
  <integer>300</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
  <key>StandardOutPath</key>
  <string>/dev/null</string>
  <key>StandardErrorPath</key>
  <string>{err_path}</string>
</dict>
</plist>
"""


def render_watchdog_template(template=PLIST_TEMPLATE, repo=REPO_ROOT, prefix=None):
    """The tracked plist template with both markers substituted.

    This is the single-company plist a person installs by hand, for a workbench
    whose only company is `paperclip/company.json`. `watchdog_plist` above is
    the per-overlay one, generated rather than tracked. Both build their label
    from the same settings prefix, so the two never disagree.
    """
    if prefix is None:
        prefix = launchd_label_prefix()
    text = Path(template).read_text()
    return text.replace(LABEL_PREFIX_MARKER, prefix).replace(WORKBENCH_MARKER, str(repo))


def _apply_module():
    spec = importlib.util.spec_from_file_location("paperclip_apply", SCRIPTS / "paperclip-apply.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", help="an overlay, such as paperclip/orgs/<name>.json")
    parser.add_argument("--apply", action="store_true", help="create and configure; default is a dry run")
    parser.add_argument("--watchdog-plist", action="store_true", help="print this company's watchdog plist")
    args = parser.parse_args(argv)

    if args.watchdog_plist:
        try:
            print(watchdog_plist(args.config), end="")
        except PaperclipError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        return 0
    try:
        client = Client(load_config(args.config)["apiBase"])
        company_id, lines = ensure_company(args.config, client, args.apply)
        for line in lines:
            print(line)
        if company_id is None:
            print("then: paperclip-apply.py hires the team into it. Run again with --apply.")
            return 0
        code = _apply_module().main(["--config", args.config] + (["--apply"] if args.apply else []))
        if code or not args.apply:
            return code
        for line in record_agent_ids(args.config, client):
            print(line)
        label = watchdog_label(args.config)
    except PaperclipError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"next: commit {args.config}, then install this company's watchdog:\n"
          f"  python3 scripts/paperclip-new-org.py {args.config} --watchdog-plist "
          f"> ~/Library/LaunchAgents/{label}.plist\n"
          f"  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{label}.plist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
