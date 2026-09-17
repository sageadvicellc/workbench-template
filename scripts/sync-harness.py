#!/usr/bin/env python3
"""Generate the per-harness files the neutral core does not carry.

A harness is the program that runs the agent loop. Each one reads its MCP
servers in its own format, from its own directory. This script renders those
files from the one copy of the source, so nothing under a harness's directory
is ever edited by hand:

- One block of MCP server tables, from the workbench's MCP source file, in the
  format the manifest names, appended to a hand-edited head.

Every path, every format identifier and every harness fact comes from
`adapters/<id>/wiring.json`. This script names no harness. A manifest holds:

    {"links": {"<path>": "<target>", ...},
     "mcp":   {"format": "<id>", "source": "<file>", "path": "<path>",
               "head": "<file>"}}

`links` is read by check-harness.py and ignored here. `mcp` is optional.
`head` is relative to the adapter directory; every other path is relative to
the workbench root.

Usage:

    python3 scripts/sync-harness.py              write what is stale
    python3 scripts/sync-harness.py --check      report, write nothing
    python3 scripts/sync-harness.py --root PATH  another tree

Exit 0 when nothing is stale, or after writing. Exit 1 from `--check` when a
generated file is missing or differs from its source. Exit 2 on an input the
script cannot use: an unreadable manifest, a format nobody registered, or an
MCP server it cannot express in the target format. Exit 2 names the file and
the cause on stderr and writes nothing.

Standard library only.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ADAPTERS_DIR = "adapters"
MANIFEST = "wiring.json"
GENERATED_MARK = "generated from {source} by scripts/sync-harness.py; do not edit below"


class SyncError(Exception):
    """An input the script cannot use. Exit 2, nothing written."""


# --- TOML rendering ----------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _escape_control(text):
    return _CONTROL.sub(lambda m: "\\u%04X" % ord(m.group()), text)


def toml_basic(text):
    """One-line basic string, quoted."""
    out = text.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + _escape_control(out) + '"'


BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _bare_key(key, where):
    """A key written unquoted in TOML. Anything else would be written as a
    dotted path or refused by the parser, and both are silent here."""
    if not isinstance(key, str) or not BARE_KEY.fullmatch(key):
        raise SyncError(f"{where}: key {key!r} is not a bare TOML key (letters, digits, _ and -)")
    return key


def render_toml_mcp_servers(servers, source_rel):
    """`[mcp_servers.<name>]` tables from the `mcpServers` object of the source
    file. Two shapes map: a local command, and a remote URL with at most a
    bearer token read from an environment variable. Anything else is refused
    by name, because a table the harness reads differently from the source
    would be a server that works on one harness and silently not the other."""
    out = [f"# --- {GENERATED_MARK.format(source=source_rel)} ---"]
    for name in sorted(servers):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise SyncError(f"{source_rel}: server {name!r}: the name must be letters, digits, _ or -")
        spec = servers[name]
        if not isinstance(spec, dict):
            raise SyncError(f"{source_rel}: server {name!r}: is not an object")
        kind = spec.get("type", "stdio")
        keys = set(spec) - {"type"}
        where = f"{source_rel}: server {name!r}"
        out.append("")
        out.append(f"[mcp_servers.{name}]")
        if kind == "stdio":
            if not isinstance(spec.get("command"), str):
                raise SyncError(f"{where}: a local server needs a command, as a string")
            if not keys <= {"command", "args", "env"}:
                extra = ", ".join(sorted(keys - {"command", "args", "env"}))
                raise SyncError(f"{where}: key(s) not rendered: {extra}")
            _no_expansion(source_rel, name, spec)
            out.append(f"command = {toml_basic(spec['command'])}")
            args = spec.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise SyncError(f"{where}: args must be a list of strings")
            out.append("args = [" + ", ".join(toml_basic(a) for a in args) + "]")
            env = spec.get("env", {})
            if env:
                if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
                    raise SyncError(f"{where}: env must map names to strings")
                out.append("")
                out.append(f"[mcp_servers.{name}.env]")
                for k in sorted(env):
                    out.append(f"{_bare_key(k, where + ' env')} = {toml_basic(env[k])}")
        elif kind in ("http", "sse"):
            if not isinstance(spec.get("url"), str):
                raise SyncError(f"{where}: a remote server needs a url, as a string")
            if not keys <= {"url", "headers"}:
                extra = ", ".join(sorted(keys - {"url", "headers"}))
                raise SyncError(f"{where}: key(s) not rendered: {extra}")
            out.append(f"url = {toml_basic(spec['url'])}")
            headers = spec.get("headers", {})
            if headers:
                if not isinstance(headers, dict):
                    raise SyncError(f"{where}: headers must be an object")
                token = _bearer_env(headers)
                if token is None:
                    raise SyncError(
                        f"{source_rel}: server {name!r}: only a header of the form "
                        f'Authorization: "Bearer ${{NAME}}" is rendered, as bearer_token_env_var')
                out.append(f"bearer_token_env_var = {toml_basic(token)}")
        else:
            raise SyncError(f"{source_rel}: server {name!r}: type {kind!r} is not rendered")
    return "\n".join(out) + "\n"


def _no_expansion(source_rel, name, spec):
    for field in ("command", "args", "env"):
        value = spec.get(field)
        blob = json.dumps(value) if value is not None else ""
        if "${" in blob:
            raise SyncError(
                f"{source_rel}: server {name!r}: {field} uses ${{...}} expansion, "
                f"which the target format does not perform")


def _bearer_env(headers):
    if list(headers) != ["Authorization"]:
        return None
    match = re.fullmatch(r"Bearer \$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(headers["Authorization"]))
    return match.group(1) if match else None


# --- sources -----------------------------------------------------------------

def _read_text(path, rel):
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SyncError(f"{rel}: cannot be read, {type(exc).__name__}")
    except UnicodeDecodeError:
        raise SyncError(f"{rel}: is not UTF-8 text")


def _read_json(path, rel):
    try:
        return json.loads(_read_text(path, rel))
    except json.JSONDecodeError as exc:
        raise SyncError(f"{rel}: is not valid JSON, {exc}")


def _contained(root, rel_path, where):
    """A relative path that stays inside the root, normalised to posix."""
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise SyncError(f"{where}: is not a path")
    if Path(rel_path).is_absolute():
        raise SyncError(f"{where}: {rel_path!r} is absolute; give a path relative to the workbench root")
    if ".." in Path(rel_path).parts:
        # No manifest path has a reason to climb. One that does is either a
        # mistake or a way to write outside the tree the script was given.
        raise SyncError(f"{where}: {rel_path!r} contains '..'; give a plain path under the workbench root")
    normal = Path(os.path.normpath(rel_path)).as_posix()
    if normal == ".":
        raise SyncError(f"{where}: {rel_path!r} is the workbench root itself")
    return normal


def load_manifests(root):
    """Every adapters/<id>/wiring.json, as (id, manifest), sorted by id."""
    adapters = root / ADAPTERS_DIR
    if not adapters.is_dir():
        return []
    found = []
    for path in sorted(adapters.glob(f"*/{MANIFEST}")):
        rel = path.relative_to(root).as_posix()
        manifest = _read_json(path, rel)
        if not isinstance(manifest, dict):
            raise SyncError(f"{rel}: the top level is not an object")
        found.append((path.parent.name, manifest))
    return found


MCP_FORMATS = {"toml-mcp-servers": render_toml_mcp_servers}


def _mcp_outputs(root, adapter, block, outputs):
    for key in ("format", "source", "path", "head"):
        if key not in block:
            raise SyncError(f"adapters/{adapter}/{MANIFEST}: mcp block has no {key!r}")
    render = MCP_FORMATS.get(block["format"])
    if render is None:
        raise SyncError(f"adapters/{adapter}/{MANIFEST}: mcp format {block['format']!r} is not registered")
    where = f"adapters/{adapter}/{MANIFEST}: mcp"
    source_rel = _contained(root, block["source"], where + ".source")
    out_rel = _contained(root, block["path"], where + ".path")
    source = _read_json(root / source_rel, source_rel)
    servers = source.get("mcpServers") if isinstance(source, dict) else None
    if not isinstance(servers, dict):
        raise SyncError(f"{source_rel}: no mcpServers object at the top level")
    head_rel = f"{ADAPTERS_DIR}/{adapter}/{block['head']}"
    head = _read_text(root / head_rel, head_rel)
    if head and not head.endswith("\n"):
        head += "\n"
    outputs[out_rel] = head + "\n" + render(servers, source_rel)


def expected_outputs(root):
    """Every generated file the manifests imply: relative posix path -> text."""
    root = Path(root)
    outputs = {}
    for adapter, manifest in load_manifests(root):
        if "mcp" in manifest:
            _mcp_outputs(root, adapter, manifest["mcp"], outputs)
    return outputs


def stale(root):
    """One line per file that is missing or differs from its source."""
    root = Path(root)
    outputs = expected_outputs(root)
    lines = []
    for rel, text in sorted(outputs.items()):
        path = root / rel
        if not path.is_file():
            lines.append(f"missing: {rel}")
        elif _read_text(path, rel) != text:
            lines.append(f"stale: {rel}")
    return lines


def write(root):
    """Write every stale or missing file."""
    root = Path(root)
    outputs = expected_outputs(root)
    lines = []
    for rel, text in sorted(outputs.items()):
        path = root / rel
        if path.is_file() and _read_text(path, rel) == text:
            lines.append(f"unchanged: {rel}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        lines.append(f"wrote: {rel}")
    return lines


def main(argv):
    args = list(argv[1:])
    root = HERE.parent
    if "--root" in args:
        i = args.index("--root")
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            print("--root needs a path", file=sys.stderr)
            return 2
        root = Path(args[i + 1])
        del args[i:i + 2]
    check = "--check" in args
    if check:
        args.remove("--check")
    if args:
        print(f"unknown argument(s): {' '.join(args)}", file=sys.stderr)
        return 2
    try:
        lines = stale(root) if check else write(root)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    if check:
        print(f"{len(lines)} stale file(s)")
        return 1 if lines else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
