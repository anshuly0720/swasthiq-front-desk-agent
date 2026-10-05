#!/usr/bin/env python3
"""Prints the tokens-and-latency table for README.md from real result files.

Reporting numbers you typed by hand is how a README ends up disagreeing with the
code. This reads results/ and results_adv/ and prints markdown, so the figures in
the README are the ones the runner actually measured.

    python metrics_table.py
    python metrics_table.py --results results results_adv
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
from typing import Dict, List


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", nargs="*", default=["results", "results_adv"],
                        type=pathlib.Path)
    args = parser.parse_args()

    rows: Dict[str, List[dict]] = {}
    for directory in args.results:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.run*.json")):
            with path.open(encoding="utf-8") as handle:
                result = json.load(handle)
            rows.setdefault(result["conversation_id"], []).append(result)

    if not rows:
        print("no results found -- run runner.py first")
        return 1

    print("| Conversation | Terminal state | Tool calls | Tokens | Latency | Source |")
    print("|---|---|---|---|---|---|")

    served, tokens_seen, latency_seen = 0, [], []
    for conversation_id in sorted(rows):
        runs = rows[conversation_id]
        first = runs[0]
        metrics = first.get("metrics", {})
        source = metrics.get("source", "?")
        tokens = metrics.get("tokens", 0)
        latency = metrics.get("latency_ms", 0)
        if source == "gemini" and tokens:
            served += 1
            tokens_seen.append(tokens)
            latency_seen.append(latency)
        state = first["terminal_state"]
        if first.get("escalation_reason"):
            state += " / " + first["escalation_reason"]
        print("| `{}` | {} | {} | {} | {} ms | {} |".format(
            conversation_id, state, len(first["tool_calls"]),
            "{:,}".format(tokens) if tokens else "—", latency, source))

    print()
    print("- Conversations measured: **{}**, of which **{}** reached the model."
          .format(len(rows), served))
    if tokens_seen:
        print("- Tokens per conversation: median **{:,}**, range {:,}-{:,}.".format(
            int(statistics.median(tokens_seen)), min(tokens_seen), max(tokens_seen)))
        print("- Latency per conversation (first, uncached): median **{:,} ms**, "
              "range {:,}-{:,} ms.".format(int(statistics.median(latency_seen)),
                                           min(latency_seen), max(latency_seen)))
    cached = [r for runs in rows.values() for r in runs[1:]]
    if cached:
        repeats = [r.get("metrics", {}).get("latency_ms", 0) for r in cached]
        print("- Repeat runs (prompt cache hit): median **{:,} ms**.".format(
            int(statistics.median(repeats))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
