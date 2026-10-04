#!/usr/bin/env python3
"""Grade results/ against the `expected` block in each conversation script.

runner.py deliberately does not grade; its README says writing that comparison
is your job. This is it, scored the way the brief says they score: every run
must pass, and the worst one is the verdict.

    python check.py
    python check.py --only cv_0011 cv_0014
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List


def load_scripts(directory: pathlib.Path, only) -> List[dict]:
    scripts = []
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            script = json.load(handle)
        if only and script.get("id") not in only:
            continue
        scripts.append(script)
    return scripts


def grade(result: dict, expected: dict) -> List[str]:
    problems = []
    called = [call["name"] for call in result.get("tool_calls", [])]

    if result.get("terminal_state") != expected.get("terminal_state"):
        problems.append(
            "terminal_state: got {!r}, want {!r}".format(
                result.get("terminal_state"), expected.get("terminal_state")
            )
        )
    if result.get("escalation_reason") != expected.get("escalation_reason"):
        problems.append(
            "escalation_reason: got {!r}, want {!r}".format(
                result.get("escalation_reason"), expected.get("escalation_reason")
            )
        )
    for tool in expected.get("must_call", []):
        if tool not in called:
            problems.append("never called {}".format(tool))
    for tool in expected.get("must_not_call", []):
        if tool in called:
            problems.append("called {} and must not have".format(tool))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="conversations", type=pathlib.Path)
    parser.add_argument("--results", default="results", type=pathlib.Path)
    parser.add_argument("--only", nargs="*", default=None, metavar="ID")
    args = parser.parse_args()

    scripts = load_scripts(args.dir, args.only)
    if not scripts:
        print("no scripts found in {}".format(args.dir), file=sys.stderr)
        return 2
    if not args.results.is_dir():
        print("no results in {} — run runner.py first".format(args.results), file=sys.stderr)
        return 2

    passed = 0
    fingerprints: Dict[str, set] = {}

    for script in scripts:
        conversation_id = script["id"]
        expected = script.get("expected", {})
        runs = sorted(args.results.glob("{}.run*.json".format(conversation_id)))

        if not runs:
            print("  MISSING  {}  (no result file)".format(conversation_id))
            continue

        worst: List[str] = []
        seen = set()
        for run_path in runs:
            with run_path.open(encoding="utf-8") as handle:
                result = json.load(handle)
            seen.add(
                "{}/{}/{}".format(
                    result.get("terminal_state"),
                    result.get("escalation_reason"),
                    ",".join(sorted({c["name"] for c in result.get("tool_calls", [])})),
                )
            )
            problems = grade(result, expected)
            if len(problems) > len(worst):
                worst = problems

        fingerprints[conversation_id] = seen
        if worst:
            print("  FAIL     {}  ({} run(s))".format(conversation_id, len(runs)))
            for problem in worst:
                print("             - {}".format(problem))
        else:
            print("  pass     {}  {}".format(conversation_id, sorted(seen)[0]))
            passed += 1

    unstable = {cid: s for cid, s in fingerprints.items() if len(s) > 1}
    print("\n{}/{} passed on their worst run".format(passed, len(scripts)))
    if unstable:
        print("\nNOT DETERMINISTIC:")
        for conversation_id, seen in unstable.items():
            print("  {}".format(conversation_id))
            for fingerprint in sorted(seen):
                print("      {}".format(fingerprint))

    return 0 if passed == len(scripts) and not unstable else 1


if __name__ == "__main__":
    raise SystemExit(main())