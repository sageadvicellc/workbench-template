"""Tests for scripts/usage-value.py: API-equivalent value of subscription use.

Transcripts are written to a temp dir. No test reads a real transcript
directory, and no test calls a network.

    uv run --quiet --with pytest python -m pytest scripts/tests -q
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
_spec = importlib.util.spec_from_file_location("usage_value", SCRIPTS / "usage-value.py")
uv = importlib.util.module_from_spec(_spec)
sys.modules["usage_value"] = uv
_spec.loader.exec_module(uv)

PRICES = {"perMTok": {
    "claude-opus-5-5": {"input": 4, "cacheWrite5m": 5, "cacheWrite1h": 8, "cacheRead": 0.2, "output": 20},
    "claude-sonnet-5": {"input": 2, "cacheWrite5m": 2.5, "cacheWrite1h": 4, "cacheRead": 0.2, "output": 10},
}}


def line(msg_id, model, ts="2026-09-26T10:00:00Z", entrypoint="cli", inp=0, out=0, read=0, w5=0, w1=0, rid="r"):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": w5 + w1,
             "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}
    return json.dumps({"type": "assistant", "timestamp": ts, "entrypoint": entrypoint, "requestId": rid,
                       "message": {"id": msg_id, "model": model, "usage": usage}})


def write(tmp, name, lines):
    p = Path(tmp) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n")
    return p


class PriceTests(unittest.TestCase):
    def test_cost_of_one_message(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
                 "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 1_000_000}}
        self.assertAlmostEqual(uv.cost(usage, PRICES["perMTok"]["claude-opus-5-5"]), 4 + 20 + 0.2 + 5 + 8)

    def test_cache_write_without_a_split_is_priced_as_5m(self):
        usage = {"cache_creation_input_tokens": 1_000_000}
        self.assertAlmostEqual(uv.cost(usage, PRICES["perMTok"]["claude-opus-5-5"]), 5)

    def test_price_lookup_matches_a_dated_model_id_by_prefix(self):
        prices = {"perMTok": {"claude-haiku-4-5": {"input": 1}, "claude-opus-5": {"input": 5},
                              "claude-opus-5-5": {"input": 4}}}
        self.assertEqual(uv.price_for("claude-haiku-4-5-20251001", prices)["input"], 1)
        self.assertEqual(uv.price_for("claude-opus-5-5", prices)["input"], 4)
        self.assertEqual(uv.price_for("claude-opus-5", prices)["input"], 5)
        self.assertIsNone(uv.price_for("gpt-5.6-sol", prices))

    def test_tracked_price_file_names_its_source_and_date(self):
        data = json.loads((REPO / "paperclip" / "api-prices.json").read_text())
        self.assertTrue(data["source"].startswith("https://"))
        self.assertRegex(data["retrieved"], r"^\d{4}-\d{2}-\d{2}$")
        for model, row in data["perMTok"].items():
            self.assertEqual(set(row), {"input", "cacheWrite5m", "cacheWrite1h", "cacheRead", "output"}, model)

    def test_the_tracked_price_file_names_no_account_or_key(self):
        """The file holds list prices and plan prices only. An account name, an
        organisation, or a key in it would be a secret in a public tree."""
        text = (REPO / "paperclip" / "api-prices.json").read_text().lower()
        for banned in ("api_key", "apikey", "secret", "bearer", "organisation", "organization"):
            self.assertNotIn(banned, text, banned)

    def test_every_tracked_price_is_priced_against_the_tracked_file(self):
        """Each model in the tracked file resolves through `price_for`, so a
        typo in a model id is a failure here rather than a silent zero."""
        prices = json.loads((REPO / "paperclip" / "api-prices.json").read_text())
        for model in prices["perMTok"]:
            self.assertIsNotNone(uv.price_for(model, prices), model)


class TallyTests(unittest.TestCase):
    def test_a_message_logged_twice_counts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", [line("m1", "claude-sonnet-5", out=1_000_000),
                                     line("m1", "claude-sonnet-5", out=1_000_000)])
            rows, unpriced = uv.tally(Path(tmp), PRICES, since="2026-09-01")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["usd"], 10)
        self.assertEqual(unpriced, {})

    def test_fleet_and_interactive_are_split_by_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", [line("m1", "claude-sonnet-5", entrypoint="sdk-ts", out=1_000_000),
                                     line("m2", "claude-sonnet-5", entrypoint="cli", out=2_000_000)])
            rows, _ = uv.tally(Path(tmp), PRICES, since="2026-09-01")
        by = {r["source"]: r["usd"] for r in rows}
        self.assertAlmostEqual(by["fleet"], 10)
        self.assertAlmostEqual(by["interactive"], 20)

    def test_subagent_transcripts_in_subfolders_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/s1/subagents/agent-1.jsonl", [line("m9", "claude-opus-5-5", out=1_000_000)])
            rows, _ = uv.tally(Path(tmp), PRICES, since="2026-09-01")
        self.assertAlmostEqual(sum(r["usd"] for r in rows), 20)

    def test_messages_before_since_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", [line("m1", "claude-sonnet-5", ts="2026-08-31T23:59:59Z", out=1_000_000)])
            rows, _ = uv.tally(Path(tmp), PRICES, since="2026-09-01")
        self.assertEqual(rows, [])

    def test_a_model_with_no_price_is_reported_not_zeroed(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", [line("m1", "claude-mystery-9", out=500)])
            rows, unpriced = uv.tally(Path(tmp), PRICES, since="2026-09-01")
        self.assertEqual(rows, [])
        self.assertEqual(unpriced, {"claude-mystery-9": 500})

    def test_a_model_the_tracked_prices_file_does_not_list_is_reported_not_zeroed(self):
        """The same rule against the tracked file rather than a fixture: an
        unlisted model never contributes a dollar, and its output tokens are
        named so a reader knows the total is short."""
        prices = json.loads((REPO / "paperclip" / "api-prices.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", [line("m1", "no-such-model-9", out=1234),
                                     line("m2", "claude-sonnet-5", out=1_000_000)])
            rows, unpriced = uv.tally(Path(tmp), prices, since="2026-09-01")
        self.assertEqual(unpriced, {"no-such-model-9": 1234})
        self.assertEqual([r["model"] for r in rows], ["claude-sonnet-5"])
        text = uv.report(rows, unpriced, subscription_usd=None)
        self.assertIn("no price for no-such-model-9", text)
        self.assertIn("1,234", text)

    def test_synthetic_and_bad_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", ["not json", json.dumps({"type": "user"}),
                                     line("m1", "<synthetic>", out=0)])
            rows, unpriced = uv.tally(Path(tmp), PRICES, since="2026-09-01")
        self.assertEqual((rows, unpriced), ([], {}))

    def test_an_empty_root_reads_nothing_and_raises_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(uv.tally(Path(tmp), PRICES, since="2026-09-01"), ([], {}))

    def test_a_root_that_does_not_exist_reads_nothing(self):
        rows, unpriced = uv.tally(Path("/nonexistent/transcripts"), PRICES, since="2026-09-01")
        self.assertEqual((rows, unpriced), ([], {}))


class SelfHostedTests(unittest.TestCase):
    PRICES = {**PRICES, "localModels": {"qwen3.5:9b": {"substitutesFor": "claude-sonnet-5"}}}

    def test_a_local_model_is_priced_at_its_substitute_as_savings(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", [line("m1", "qwen3.5:9b", out=1_000_000)])
            rows, unpriced = uv.tally(Path(tmp), self.PRICES, since="2026-09-01")
        self.assertEqual([(r["source"], r["model"]) for r in rows], [("self-hosted", "qwen3.5:9b")])
        self.assertAlmostEqual(rows[0]["usd"], 10)
        self.assertEqual(unpriced, {})

    def test_savings_are_reported_apart_from_subscription_value(self):
        rows = [{"date": "d", "source": "interactive", "model": "claude-sonnet-5", "usd": 300.0, "output": 0},
                {"date": "d", "source": "self-hosted", "model": "qwen3.5:9b", "usd": 12.0, "output": 0}]
        text = uv.report(rows, {}, plans={"anthropic": {"name": "Anthropic plan", "monthlyUsd": 200}})
        self.assertIn("self-hosted savings: $12.00", text)
        self.assertIn("Anthropic plan: $300.00 against $200.00 a month, 1.50x", text)


class PlanTests(unittest.TestCase):
    def test_the_tracked_file_holds_a_plan_price_per_provider(self):
        data = json.loads((REPO / "paperclip" / "api-prices.json").read_text())
        self.assertEqual(data["plans"]["anthropic"]["monthlyUsd"], 200)
        self.assertEqual(data["plans"]["openai"]["monthlyUsd"], 100)

    def test_provider_of_a_model(self):
        self.assertEqual(uv.provider("claude-opus-5-5"), "anthropic")
        self.assertEqual(uv.provider("gpt-5.6-sol"), "openai")
        self.assertIsNone(uv.provider("qwen3.5:9b"))


class ReportTests(unittest.TestCase):
    def test_report_totals_and_names_the_subscription_gap(self):
        rows = [{"date": "2026-09-26", "source": "fleet", "model": "claude-opus-5", "usd": 12.5,
                 "input": 1, "output": 2, "cacheRead": 3, "cacheWrite": 4}]
        text = uv.report(rows, {"gpt-5.6-sol": 84}, subscription_usd=None)
        self.assertIn("12.50", text)
        self.assertIn("gpt-5.6-sol", text)
        self.assertIn("--subscription-usd", text)

    def test_report_gives_a_multiple_when_the_plan_price_is_known(self):
        rows = [{"date": "2026-09-26", "source": "fleet", "model": "m", "usd": 400.0,
                 "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}]
        self.assertIn("2.00x", uv.report(rows, {}, subscription_usd=200))

    def test_plans_give_a_multiple_per_provider(self):
        rows = [{"date": "d", "source": "fleet", "model": "claude-opus-5", "usd": 400.0, "output": 0}]
        text = uv.report(rows, {}, plans={"anthropic": {"name": "Anthropic plan", "monthlyUsd": 200},
                                          "openai": {"name": "OpenAI plan", "monthlyUsd": 100}})
        self.assertIn("Anthropic plan: $400.00 against $200.00 a month, 2.00x", text)
        self.assertIn("OpenAI plan: no usage read yet", text)

    def test_an_empty_report_still_names_the_plans(self):
        text = uv.report([], {}, plans={"anthropic": {"name": "Anthropic plan", "monthlyUsd": 200}})
        self.assertIn("total: $0.00", text)
        self.assertIn("no usage read yet", text)


class CliTests(unittest.TestCase):
    """`--root` has no default, because a default would name one harness's
    transcript directory and nothing in this tree may name a harness."""

    def test_root_is_required(self):
        with self.assertRaises(SystemExit):
            uv.main([])

    def test_a_run_against_a_temp_root_prints_a_table(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "p/a.jsonl", [line("m1", "claude-sonnet-5", out=1_000_000)])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = uv.main(["--root", tmp, "--since", "2026-09-01"])
        self.assertEqual(code, 0)
        self.assertIn("claude-sonnet-5", out.getvalue())

    def test_json_output_parses_and_carries_the_price_provenance(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                uv.main(["--root", tmp, "--since", "2026-09-01", "--json"])
        data = json.loads(out.getvalue())
        self.assertTrue(data["prices"].startswith("https://"))
        self.assertRegex(data["retrieved"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(data["rows"], [])


if __name__ == "__main__":
    unittest.main()
