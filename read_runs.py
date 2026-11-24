#!/usr/bin/env python3
"""Print run transcripts with the private channels included.

The Inspect log viewer shows the conversation. This shows the conversation plus
each side's reasoning and scratchpad, interleaved in order, which is the view you
want when the question is "where did it get confused" rather than "did it close".

    python read_runs.py logs/v1-vA_2026-09-29
    python read_runs.py logs/v1-vA_2026-09-29 --outcome max_turns --limit 5
    python read_runs.py logs/... --role seller --thinking-only
"""

from __future__ import annotations

import argparse
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

RULE = "=" * 78


def iter_samples(log_dir: Path):
    for info in list_eval_logs(str(log_dir)):
        log = read_eval_log(info)
        model = getattr(log.eval, "model", "?")
        for sample in log.samples or []:
            yield model, sample


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log_dir", type=Path)
    ap.add_argument("--outcome", default=None,
                    help="only runs with this outcome (payment_sent, max_turns, buyer_walked)")
    ap.add_argument("--model", default=None, help="substring match on model name")
    ap.add_argument("--role", choices=["seller", "buyer"], default=None)
    ap.add_argument("--thinking-only", action="store_true",
                    help="skip turns that produced no reasoning or scratchpad")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    shown = 0
    for model, sample in iter_samples(args.log_dir):
        if shown >= args.limit:
            break
        md = sample.metadata or {}
        outcome = md.get("outcome")
        if args.outcome and outcome != args.outcome:
            continue
        if args.model and args.model not in str(model):
            continue

        transcript = md.get("transcript") or []
        entries = [e for e in transcript if not args.role or e["role"] == args.role]
        if args.thinking_only:
            entries = [e for e in entries if e.get("reasoning") or e.get("scratchpad")]
        if not entries:
            continue

        shown += 1
        print(f"\n{RULE}\n{model}   outcome={outcome}   "
              f"turns={md.get('turns_used')}   epoch={getattr(sample, 'epoch', '?')}\n{RULE}")

        for entry in entries:
            speaker = entry["role"].upper()
            print(f"\n--- turn {entry['turn']} :: {speaker} ---")
            if entry.get("reasoning"):
                print(f"\n[native reasoning]\n{entry['reasoning']}")
            if entry.get("scratchpad"):
                print(f"\n[scratchpad]\n{entry['scratchpad']}")
            print(f"\n[message]\n{entry['text']}")

    if shown == 0:
        print("No runs matched. Check --outcome / --model, or confirm the log dir.")
    else:
        print(f"\n{RULE}\nshown: {shown}")


if __name__ == "__main__":
    main()
