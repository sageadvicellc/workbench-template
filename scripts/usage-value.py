#!/usr/bin/env python3
"""What this workbench's model use would cost at API list prices.

A fleet that bills on a subscription has no dollar figure for its runs. This
script puts one on them, for the return on the subscription: it reads every
agent transcript under the directory `--root` names, prices each assistant
message by its model from `paperclip/api-prices.json`, and totals by day, by
source, and by model.

    python3 scripts/usage-value.py --root <transcripts>                    # this month
    python3 scripts/usage-value.py --root <transcripts> --since 2026-09-01
    python3 scripts/usage-value.py --root <transcripts> --subscription-usd 200
    python3 scripts/usage-value.py --root <transcripts> --json

`--root` is required and has no default, because a default would name one
harness's transcript directory and no script in this tree names a harness. It is
the directory holding JSON Lines transcripts, one object per line, read
recursively. A transcript in a subfolder, such as a subagent's, is counted too.

A source is `fleet` when a transcript line's `entrypoint` is one of
`FLEET_ENTRYPOINTS`, the software development kit entry points an agent runtime
uses, and `interactive` otherwise. A message logged more than once counts once.
A model with no price is listed with its output tokens, never priced at zero.
Reads files only; changes nothing.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRICES = REPO / "paperclip" / "api-prices.json"
FLEET_ENTRYPOINTS = {"sdk-ts", "sdk-py"}
MTOK = 1_000_000


def provider(model):
    """The plan a model's use counts against: a key in the prices file's `plans`,
    or None for a self-hosted model."""
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return None


def price_for(model, prices):
    """The longest model id in the price table that `model` starts with."""
    best = None
    for key in prices["perMTok"]:
        if model == key or model.startswith(key + "-"):
            if best is None or len(key) > len(best):
                best = key
    return prices["perMTok"][best] if best else None


def cost(usage, row):
    """USD for one message's `usage` at one price row."""
    creation = usage.get("cache_creation") or {}
    w5 = creation.get("ephemeral_5m_input_tokens")
    w1 = creation.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5, w1 = usage.get("cache_creation_input_tokens") or 0, 0
    return ((usage.get("input_tokens") or 0) * row.get("input", 0)
            + (usage.get("output_tokens") or 0) * row.get("output", 0)
            + (usage.get("cache_read_input_tokens") or 0) * row.get("cacheRead", 0)
            + (w5 or 0) * row.get("cacheWrite5m", 0)
            + (w1 or 0) * row.get("cacheWrite1h", 0)) / MTOK


def _messages(root):
    root = Path(root)
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.jsonl")):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            msg = entry.get("message") if isinstance(entry, dict) else None
            if entry.get("type") == "assistant" and isinstance(msg, dict) and msg.get("usage"):
                yield entry, msg


def tally(root, prices, since):
    """Rows of {date, source, model, usd, input, output, cacheRead, cacheWrite},
    and unpriced output by model."""
    seen = set()
    sums = collections.defaultdict(collections.Counter)
    unpriced = collections.Counter()
    for entry, msg in _messages(root):
        day = (entry.get("timestamp") or "")[:10]
        model = msg.get("model") or ""
        if day < since or model.startswith("<"):
            continue
        key = (msg.get("id"), entry.get("requestId"))
        if key in seen:
            continue
        seen.add(key)
        usage = msg["usage"]
        local = (prices.get("localModels") or {}).get(model)
        if local:
            # A self-hosted model's tokens are priced at the API model it stands
            # in for: money saved.
            row, source = prices["perMTok"].get(local["substitutesFor"]), "self-hosted"
        else:
            row = price_for(model, prices)
            source = "fleet" if entry.get("entrypoint") in FLEET_ENTRYPOINTS else "interactive"
        if row is None:
            unpriced[model] += usage.get("output_tokens") or 0
            continue
        s = sums[(day, source, model)]
        s["usd"] += cost(usage, row)
        s["input"] += usage.get("input_tokens") or 0
        s["output"] += usage.get("output_tokens") or 0
        s["cacheRead"] += usage.get("cache_read_input_tokens") or 0
        s["cacheWrite"] += usage.get("cache_creation_input_tokens") or 0
    rows = [{"date": d, "source": src, "model": m, **dict(s)} for (d, src, m), s in sorted(sums.items())]
    return rows, dict(unpriced)


def report(rows, unpriced, subscription_usd=None, plans=None):
    lines = ["| Date | Source | Model | Output tokens | API-equivalent USD |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['date']} | {r['source']} | {r['model']} | {r['output']:,} | {r['usd']:.2f} |")
    by_source = collections.Counter()
    for r in rows:
        by_source[r["source"]] += r["usd"]
    savings = by_source.pop("self-hosted", 0)
    total = sum(by_source.values())
    lines.append("")
    for source, usd in sorted(by_source.items()):
        lines.append(f"{source}: ${usd:,.2f}")
    lines.append(f"total: ${total:,.2f}")
    if subscription_usd:
        lines.append(f"multiple of the plan price (${subscription_usd:,.2f}): {total / subscription_usd:.2f}x")
    elif plans:
        for key, plan in plans.items():
            value = sum(r["usd"] for r in rows if r["source"] != "self-hosted" and provider(r["model"]) == key)
            monthly = plan["monthlyUsd"]
            if value:
                lines.append(f"{plan['name']}: ${value:,.2f} against ${monthly:,.2f} a month, "
                             f"{value / monthly:.2f}x")
            else:
                lines.append(f"{plan['name']}: no usage read yet, against ${monthly:,.2f} a month")
    else:
        lines.append("plan price unknown: pass --subscription-usd to get the multiple")
    if savings:
        lines.append(f"self-hosted savings: ${savings:,.2f}")
    for model, out in sorted(unpriced.items()):
        lines.append(f"no price for {model}: {out:,} output tokens left out of the total")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True,
                       help="the directory of agent transcripts, JSON Lines, read recursively")
    parser.add_argument("--since", default=date.today().replace(day=1).isoformat(),
                        help="YYYY-MM-DD, inclusive; default is the first of this month")
    parser.add_argument("--prices", default=str(PRICES))
    parser.add_argument("--subscription-usd", type=float, help="the plan's price over the same period")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    prices = json.loads(Path(args.prices).read_text())
    rows, unpriced = tally(Path(args.root), prices, args.since)
    if args.json:
        print(json.dumps({"since": args.since, "prices": prices["source"], "retrieved": prices["retrieved"],
                          "plans": prices.get("plans") or {}, "rows": rows, "unpriced": unpriced}, indent=2))
    else:
        print(f"API-equivalent value since {args.since}, list prices from {prices['source']} "
              f"(retrieved {prices['retrieved']})\n")
        print(report(rows, unpriced, args.subscription_usd, plans=prices.get("plans")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
