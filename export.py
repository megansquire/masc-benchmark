#!/usr/bin/env python3
"""Dump every conversation to plain text you can read, grep and hand-code.

    python export.py logs/phase1_v4-conduct_v6_2026-10-29

Writes into <log_dir>/export/:

    index.csv                        one row per conversation
    conversations/<model>/<persona>-<epoch>.txt

Nothing is interpreted. The text files are the conversations as they happened,
plus whatever the model was thinking where that was captured. index.csv carries
the facts you need to sample and sort, blank columns for your codes, and the
automated labels to compare against afterwards. The codes are in CODING.md.

Run rescore.py first: the automated labels come from rescored.json.

This reads the .eval files for you - you never have to open Inspect.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from masc_benchmark.recognition import _opaque, detect
from report import best_logs, code_for, load_rescored


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def render_turns(md) -> list[str]:
    """The conversation itself, with each side's thinking where it was shown."""
    out = []
    for e in md.get("transcript", []):
        who = str(e.get("role", "")).upper()
        if e.get("reasoning") and _opaque(str(e["reasoning"])):
            out.append(f"  [{who} thinking: encrypted by the provider, not readable]")
            out.append("")
        elif e.get("reasoning"):
            out.append(f"  [{who} thinking]")
            for line in str(e["reasoning"]).splitlines():
                out.append(f"    {line}")
            out.append("")
        out.append(f"{who}: {e.get('text','')}")
        out.append("")
    return out


def render(model, persona, epoch, md, scores, auto) -> str:
    conduct = scores.get("conduct")
    out = [
        f"model    : {model}",
        f"persona  : {persona}",
        f"epoch    : {epoch}",
        f"turns    : {md.get('turns_used')}",
        f"",
        f"outcome     : ______________   REFUSED WARNED PAID CONCEDED WALKED INCONCLUSIVE",
        f"recognised  : ______________   yes / no / n/a",
        f"test-aware  : ______________   yes / no / n/a        (see CODING.md)",
        f"",
        "=" * 78,
        "",
    ]
    out += render_turns(md)
    # Below the conversation so they are read after coding, not before.
    out += [
        "=" * 78,
        "automated labels - compare AFTER coding",
        f"  outcome    : {auto['outcome']}   (harness: {auto['harness']})",
        f"  recognised : {auto['recognised']}   test-aware: {auto['test_aware']}"
        f"   seller trace: {auto['trace']}",
        f"  grader     : {getattr(conduct, 'answer', None)}"
        f" - {getattr(conduct, 'explanation', '') or ''}",
    ]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()

    out = args.out or args.log_dir / "export"
    convo_dir = out / "conversations"
    convo_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    fixed = load_rescored(args.log_dir)
    if not fixed:
        print("note: no rescored.json - run rescore.py first for corrected labels")

    for (model, persona), (_, _, samples) in sorted(best_logs(args.log_dir).items()):
        d = convo_dir / safe(model)
        d.mkdir(parents=True, exist_ok=True)

        for i, s in enumerate(samples, 1):
            md = s.metadata or {}
            scores = s.scores or {}
            conduct = scores.get("conduct")
            cv = getattr(conduct, "value", {}) or {}
            corr = fixed.get(f"{model}|{persona}|{i}") or {}
            harness = corr.get("outcome", md.get("outcome"))
            code, played = code_for(harness, corr.get("refusal_mode"))
            seen = detect(md.get("transcript", []) or [])
            auto = {"outcome": code, "harness": harness, **seen}

            path = d / f"{persona}-{i:02d}.txt"
            path.write_text(render(model, persona, i, md, scores, auto),
                            encoding="utf-8")

            seller = " ".join(e.get("text", "") for e in md.get("transcript", [])
                              if e.get("role") == "seller")
            rows.append({
                "model": model,
                "persona": persona,
                "epoch": i,
                "turns": md.get("turns_used"),
                "seller_trace": seen["trace"],
                "seller_words": len(seller.split()),
                "file": str(path.relative_to(out)),
                "my_outcome": "",
                "my_recognised": "",
                "my_test_aware": "",
                "my_notes": "",
                "auto_outcome": code,
                "auto_played": played,
                "auto_recognised": seen["recognised"],
                "auto_test_aware": seen["test_aware"],
                "harness_label": harness,
                "grader_label": getattr(conduct, "answer", None),
                "partial_payment": cv.get("prepaid_partial"),
            })

    rows.sort(key=lambda r: (r["model"], r["persona"], r["epoch"]))
    with (out / "index.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)} conversations -> {out}")
    print(f"  index.csv        (fill in my_outcome, my_recognised, my_test_aware)")
    print(f"  conversations/   (one readable .txt per conversation)")


if __name__ == "__main__":
    main()
