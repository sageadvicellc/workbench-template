"""Tests for scripts/sync-harness.py.

The script renders, per adapter manifest, the generated files a harness needs
that the neutral core does not carry: one block of MCP server tables from the
workbench's MCP source, in the harness's own format. Every path and format
identifier comes from adapters/*/wiring.json; the script names no harness.

Standard library only. Run with:

    python3 -m unittest discover -s scripts/tests
"""

import ast
import importlib.util
import json
import re
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "sync-harness.py"
WORKBENCH_ROOT = SCRIPT_PATH.parent.parent

_spec = importlib.util.spec_from_file_location("sync_harness", SCRIPT_PATH)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)

MCP_MANIFEST = {
    "links": {},
    "mcp": {"format": "toml-mcp-servers", "source": ".mcp.json",
            "path": ".x/config.toml", "head": "config.toml"},
}


class Fixture:
    """A workbench tree under a temporary directory: one pack skill, one
    adapter, and an MCP source with one local server in it."""

    def __init__(self, manifest=None, servers=None, head="# head line\n"):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write("wiki/skills/one/SKILL.md", "---\nname: one\ndescription: d\n---\n")
        self.write("adapters/x/wiring.json", json.dumps(manifest or MCP_MANIFEST))
        self.write("adapters/x/config.toml", head)
        self.write(".mcp.json", json.dumps(
            {"mcpServers": servers if servers is not None else {"local": {"command": "run"}}}))

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def cleanup(self):
        self._tmp.cleanup()


class SyncHarnessTest(unittest.TestCase):

    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.root = self.fx.root

    def _mcp_tree(self, servers, head="# head line\n"):
        self.fx.write("adapters/x/wiring.json", json.dumps(MCP_MANIFEST))
        self.fx.write("adapters/x/config.toml", head)
        self.fx.write(".mcp.json", json.dumps({"mcpServers": servers}))

    # -- TOML string rendering ------------------------------------------------

    def test_basic_string_escapes_backslash_quote_newline_and_control(self):
        self.assertEqual(sync.toml_basic('a\\b"c\nd\te\x01'), '"a\\\\b\\"c\\nd\\te\\u0001"')

    # -- expected outputs from the manifests ----------------------------------

    def test_manifest_without_an_mcp_block_produces_nothing(self):
        self.fx.write("adapters/x/wiring.json", json.dumps({"links": {"L": "T"}}))
        self.assertEqual(sync.expected_outputs(self.root), {})

    def test_one_output_per_manifest_that_declares_mcp(self):
        outputs = sync.expected_outputs(self.root)
        self.assertEqual(sorted(outputs), [".x/config.toml"])

    def test_unknown_format_identifier_is_an_input_error(self):
        manifest = {"mcp": {"format": "yaml-thing", "source": ".mcp.json",
                            "path": ".x/config.toml", "head": "config.toml"}}
        self.fx.write("adapters/x/wiring.json", json.dumps(manifest))
        with self.assertRaises(sync.SyncError) as ctx:
            sync.expected_outputs(self.root)
        self.assertIn("yaml-thing", str(ctx.exception))

    def test_mcp_block_missing_a_key_is_an_input_error_naming_it(self):
        manifest = {"mcp": {"format": "toml-mcp-servers", "source": ".mcp.json",
                            "path": ".x/config.toml"}}
        self.fx.write("adapters/x/wiring.json", json.dumps(manifest))
        with self.assertRaises(sync.SyncError) as ctx:
            sync.expected_outputs(self.root)
        self.assertIn("head", str(ctx.exception))

    def test_unreadable_manifest_json_is_an_input_error_naming_the_file(self):
        self.fx.write("adapters/x/wiring.json", "{not json")
        with self.assertRaises(sync.SyncError) as ctx:
            sync.expected_outputs(self.root)
        self.assertIn("adapters/x/wiring.json", str(ctx.exception))

    # -- inputs the review found unguarded, 2026-09-12 --------------------------

    def test_an_output_path_that_escapes_the_root_is_an_input_error(self):
        for bad in (".x/config.toml/..", "/tmp/elsewhere", "../outside"):
            with self.subTest(path=bad):
                manifest = {"mcp": {"format": "toml-mcp-servers", "source": ".mcp.json",
                                    "path": bad, "head": "config.toml"}}
                self.fx.write("adapters/x/wiring.json", json.dumps(manifest))
                with self.assertRaises(sync.SyncError) as ctx:
                    sync.stale(self.root)
                self.assertIn("path", str(ctx.exception))

    def test_env_key_that_is_not_a_bare_toml_key_is_an_input_error(self):
        self._mcp_tree({"s": {"command": "c", "env": {"MY.VAR": "1"}}})
        with self.assertRaises(sync.SyncError) as ctx:
            sync.expected_outputs(self.root)
        self.assertIn("MY.VAR", str(ctx.exception))

    def test_wrong_json_types_are_input_errors_not_tracebacks(self):
        self._mcp_tree({"s": {"command": 123}})
        with self.assertRaises(sync.SyncError):
            sync.expected_outputs(self.root)
        self._mcp_tree({"s": {"type": "http", "url": "u", "headers": ["x"]}})
        with self.assertRaises(sync.SyncError):
            sync.expected_outputs(self.root)
        self.fx.write(".mcp.json", json.dumps(["not", "an", "object"]))
        with self.assertRaises(sync.SyncError):
            sync.expected_outputs(self.root)

    def test_non_utf8_head_or_generated_file_is_an_input_error(self):
        self._mcp_tree({})
        (self.root / "adapters/x/config.toml").write_bytes(b"# caf\xe9\n")
        with self.assertRaises(sync.SyncError) as ctx:
            sync.expected_outputs(self.root)
        self.assertIn("adapters/x/config.toml", str(ctx.exception))
        self.fx.write("adapters/x/config.toml", "# ok\n")
        sync.write(self.root)
        (self.root / ".x/config.toml").write_bytes(b"\xff\xfe")
        with self.assertRaises(sync.SyncError) as ctx:
            sync.stale(self.root)
        self.assertIn(".x/config.toml", str(ctx.exception))

    def test_root_flag_without_a_path_exits_2_even_before_check(self):
        result = self._cli("--root", "--check")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--root needs a path", result.stderr)

    # -- stale and write --------------------------------------------------------

    def test_stale_reports_every_missing_file_before_the_first_write(self):
        self.assertEqual(sync.stale(self.root), ["missing: .x/config.toml"])

    def test_write_then_stale_is_clean(self):
        lines = sync.write(self.root)
        self.assertEqual(lines, ["wrote: .x/config.toml"])
        self.assertEqual(sync.stale(self.root), [])
        self.assertTrue((self.root / ".x/config.toml").is_file())

    def test_edited_output_is_reported_stale(self):
        sync.write(self.root)
        path = self.root / ".x/config.toml"
        path.write_text(path.read_text(encoding="utf-8") + "# hand edit\n", encoding="utf-8")
        self.assertEqual(sync.stale(self.root), ["stale: .x/config.toml"])

    def test_write_reports_unchanged_files_as_unchanged(self):
        sync.write(self.root)
        self.assertEqual(sync.write(self.root), ["unchanged: .x/config.toml"])

    # -- MCP servers ------------------------------------------------------------

    @unittest.skipUnless(tomllib, "tomllib needs Python 3.11")
    def test_local_server_maps_command_args_and_env(self):
        self._mcp_tree({"local": {
            "command": "npx", "args": ["-y", "some-server"], "env": {"TOKEN_FILE": "/tmp/t"}}})
        text = sync.expected_outputs(self.root)[".x/config.toml"]
        doc = tomllib.loads(text)
        self.assertEqual(doc["mcp_servers"]["local"]["command"], "npx")
        self.assertEqual(doc["mcp_servers"]["local"]["args"], ["-y", "some-server"])
        self.assertEqual(doc["mcp_servers"]["local"]["env"], {"TOKEN_FILE": "/tmp/t"})

    @unittest.skipUnless(tomllib, "tomllib needs Python 3.11")
    def test_remote_server_maps_url_and_bearer_token_variable(self):
        self._mcp_tree({"remote": {
            "type": "http", "url": "https://example.test/mcp",
            "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}}})
        doc = tomllib.loads(sync.expected_outputs(self.root)[".x/config.toml"])
        self.assertEqual(doc["mcp_servers"]["remote"]["url"], "https://example.test/mcp")
        self.assertEqual(doc["mcp_servers"]["remote"]["bearer_token_env_var"], "REMOTE_TOKEN")

    def test_head_comes_first_then_the_marker_then_the_tables(self):
        self._mcp_tree({"a": {"command": "c"}}, head="# my head\n")
        text = sync.expected_outputs(self.root)[".x/config.toml"]
        lines = text.splitlines()
        self.assertEqual(lines[0], "# my head")
        self.assertTrue(any("do not edit below" in l for l in lines))
        self.assertLess(lines.index(next(l for l in lines if "do not edit below" in l)),
                        lines.index("[mcp_servers.a]"))

    def test_empty_source_yields_head_and_marker_only(self):
        self._mcp_tree({})
        text = sync.expected_outputs(self.root)[".x/config.toml"]
        self.assertNotIn("[mcp_servers", text)
        self.assertIn("do not edit below", text)

    def test_missing_source_is_an_input_error_naming_it(self):
        self._mcp_tree({})
        (self.root / ".mcp.json").unlink()
        with self.assertRaises(sync.SyncError) as ctx:
            sync.expected_outputs(self.root)
        self.assertIn(".mcp.json", str(ctx.exception))

    def _rejects(self, servers, *needles):
        self._mcp_tree(servers)
        with self.assertRaises(sync.SyncError) as ctx:
            sync.expected_outputs(self.root)
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))

    def test_rejects_expansion_in_a_local_server(self):
        self._rejects({"s": {"command": "run", "env": {"K": "${HOME}/x"}}}, "'s'", "expansion")

    def test_rejects_a_header_that_is_not_a_bearer_variable(self):
        self._rejects({"s": {"type": "http", "url": "https://x", "headers": {"X-Key": "abc"}}},
                      "'s'", "bearer_token_env_var")

    def test_rejects_a_literal_bearer_token(self):
        self._rejects({"s": {"type": "http", "url": "https://x",
                             "headers": {"Authorization": "Bearer abc123"}}}, "'s'")

    def test_rejects_an_unknown_key(self):
        self._rejects({"s": {"command": "run", "timeout": 5}}, "'s'", "timeout")

    def test_rejects_a_server_name_that_is_not_a_bare_toml_key(self):
        self._rejects({"my server": {"command": "run"}}, "'my server'")

    def test_rejects_a_local_server_with_no_command(self):
        self._rejects({"s": {"args": ["x"]}}, "'s'", "command")

    def test_rejects_an_unknown_type(self):
        self._rejects({"s": {"type": "grpc", "url": "u"}}, "'s'", "grpc")

    # -- the command line -------------------------------------------------------

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=self.root,
        )

    def test_check_exits_1_and_names_the_path_and_writes_nothing(self):
        result = self._cli("--check", "--root", str(self.root))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("missing: .x/config.toml", result.stdout)
        self.assertFalse((self.root / ".x").exists())

    def test_default_run_writes_and_exits_0_then_check_exits_0(self):
        result = self._cli("--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("wrote: .x/config.toml", result.stdout)
        result = self._cli("--check", "--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_input_error_exits_2_and_names_the_cause_on_stderr(self):
        self.fx.write("adapters/x/wiring.json", "{not json")
        result = self._cli("--check", "--root", str(self.root))
        self.assertEqual(result.returncode, 2)
        self.assertIn("adapters/x/wiring.json", result.stderr)

    def test_a_tree_with_no_adapters_directory_generates_nothing(self):
        import shutil
        shutil.rmtree(self.root / "adapters")
        result = self._cli("--check", "--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 stale file(s)", result.stdout)

    def test_check_leaves_no_bytecode_cache_behind(self):
        """Other test files load the scripts through importlib and leave
        scripts/__pycache__ behind. Only the file this script would write is
        cleared first and checked after."""
        cache = WORKBENCH_ROOT / "scripts" / "__pycache__"
        for pyc in cache.glob("sync-harness.*.pyc"):
            pyc.unlink()
        self._cli("--check", "--root", str(self.root))
        self.assertEqual([p.name for p in cache.glob("sync-harness.*.pyc")], [])
        self.assertEqual(list(self.root.rglob("__pycache__")), [])

    # -- housekeeping -----------------------------------------------------------

    def test_script_imports_nothing_outside_the_standard_library(self):
        stdlib_dir = Path(sysconfig.get_paths()["stdlib"]).resolve()
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        self.assertTrue(names)
        for name in names:
            spec = importlib.util.find_spec(name)
            self.assertIsNotNone(spec, f"{name} is not importable")
            origin = spec.origin
            is_builtin = origin in (None, "built-in", "frozen")
            is_stdlib = bool(origin) and Path(origin).resolve().is_relative_to(stdlib_dir) \
                and "site-packages" not in origin
            self.assertTrue(is_builtin or is_stdlib, f"{name} is not standard library")

    def test_script_names_no_harness(self):
        """scripts/ is in the neutral core. Every harness path comes from data,
        and the pattern this test applies comes from the names file, so the
        test never has to name a harness either."""
        names = WORKBENCH_ROOT / "adapters" / "harness-names.txt"
        lines = [l.strip() for l in names.read_text(encoding="utf-8").splitlines()]
        pattern = re.compile("|".join(f"(?:{l})" for l in lines if l and not l.startswith("#")),
                             re.IGNORECASE)
        for lineno, line in enumerate(SCRIPT_PATH.read_text(encoding="utf-8").splitlines(), 1):
            self.assertIsNone(pattern.search(line), f"line {lineno} names a harness")

    def test_the_script_carries_no_role_rendering(self):
        """The template ships no roles. A renderer left behind here would
        generate files from a source that no longer exists."""
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for gone in ("agents/", "render_toml_agent", "ROLE_FORMATS", "role_sources", "orphan"):
            self.assertNotIn(gone, source)

    def test_the_shipped_tree_is_current(self):
        """The committed generated files match their sources byte for byte."""
        self.assertEqual(sync.stale(WORKBENCH_ROOT), [])


if __name__ == "__main__":
    unittest.main()
