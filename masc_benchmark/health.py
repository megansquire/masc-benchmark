"""Instrument health check over a directory of eval logs.

Answers one question: is the harness measuring what it claims to measure, or is
it broken in a way that would quietly corrupt the results? Every number here has
been a real bug at some point in this project.

Used automatically at the end of every `ladder.py` run, and standalone:

    python -m masc_benchmark.health logs/ladder_v4-conduct_v5_scratchpad_...
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log


@dataclass
class Health:
    runs: int = 0
    contaminated: int = 0
    contaminated_turns: int = 0
    disagreements: int = 0
    grader_failed: int = 0
    scratchpad_runs: int = 0
    reasoning_runs: int = 0
    empty_messages: int = 0
    refusals: int = 0
    self_defeats: int = 0
    at_turn_cap: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return (
            self.contaminated == 0
            and self.disagreements == 0
            and self.grader_failed == 0
            and self.empty_messages == 0
        )


def collect(log_dir: str | Path) -> Health:
    h = Health()
    for info in list_eval_logs(str(log_dir)):
        log = read_eval_log(info)
        for s in log.samples or []:
            md = s.metadata or {}
            h.runs += 1

            if md.get("contaminated_turns"):
                h.contaminated += 1
                h.contaminated_turns += int(md["contaminated_turns"])
                if len(h.examples) < 3:
                    leaked = next(
                        (e for e in md.get("transcript", []) if e.get("contaminated")),
                        None,
                    )
                    if leaked:
                        h.examples.append(
                            f"{leaked['role']} turn {leaked['turn']}: "
                            f"{str(leaked['text'])[:90]}"
                        )

            o = md.get("outcome")
            if o in ("seller_refused", "buyer_refused"):
                h.refusals += 1
            if o == "agreed_on_delivery":
                h.self_defeats += 1

            if md.get("turns_used") and md.get("max_turns"):
                if md["turns_used"] >= md["max_turns"]:
                    h.at_turn_cap += 1

            if (md.get("buyer_scratchpad_turns") or 0) + (
                md.get("seller_scratchpad_turns") or 0
            ):
                h.scratchpad_runs += 1
            if (md.get("buyer_reasoning_turns") or 0) + (
                md.get("seller_reasoning_turns") or 0
            ):
                h.reasoning_runs += 1

            h.empty_messages += sum(
                1 for e in md.get("transcript", []) if not str(e.get("text", "")).strip()
            )

            scores = s.scores or {}
            conduct = scores.get("conduct")
            if conduct is not None:
                meta = getattr(conduct, "metadata", None) or {}
                if meta.get("agrees_with_harness") is False:
                    h.disagreements += 1
                value = getattr(conduct, "value", None)
                if isinstance(value, dict) and value.get("grader_failed"):
                    h.grader_failed += 1
    return h


def render(h: Health) -> str:
    if h.runs == 0:
        return "No runs found in that log directory."

    def line(label: str, count: int, good_is_zero: bool = True, note: str = "") -> str:
        if good_is_zero:
            mark = "ok  " if count == 0 else "FAIL"
        else:
            mark = "ok  " if count == h.runs else "warn"
        return f"  [{mark}] {label:<34}{count:>4} / {h.runs}   {note}"

    out = ["", f"INSTRUMENT HEALTH  ({h.runs} runs)", "-" * 72]
    out.append(line("runs leaking private reasoning", h.contaminated,
                    note="scratchpad reached the other bot"))
    out.append(line("harness/grader disagreements", h.disagreements,
                    note="hard rule vs model grader"))
    out.append(line("grader output unparseable", h.grader_failed))
    out.append(line("empty messages sent", h.empty_messages,
                    note="model spent its budget reasoning: raise max_tokens"))
    out.append(line("runs with a scratchpad captured", h.scratchpad_runs,
                    good_is_zero=False,
                    note="0 means --scratchpad is off or ignored"))
    out.append(line("runs with native reasoning", h.reasoning_runs,
                    good_is_zero=False,
                    note="0 is normal for non-thinking models"))
    out.append(f"  [    ] {'runs that hit the turn cap':<34}{h.at_turn_cap:>4} / {h.runs}"
               f"   high means max_turns is too low")

    if h.examples:
        out.append("")
        out.append("  leaked text, first few:")
        for e in h.examples:
            out.append(f"    {e}")

    out.append("")
    if h.clean:
        out.append("  VERDICT: clean. Results from this run are usable.")
    else:
        bad = []
        if h.contaminated:
            bad.append(f"{h.contaminated} contaminated run(s)")
        if h.disagreements:
            bad.append(f"{h.disagreements} scorer disagreement(s)")
        if h.grader_failed:
            bad.append(f"{h.grader_failed} grader failure(s)")
        if h.empty_messages:
            bad.append(f"{h.empty_messages} empty message(s)")
        out.append(f"  VERDICT: NOT clean - {', '.join(bad)}.")
        out.append("  Exclude the affected runs or fix and rerun before using these numbers.")
    return "\n".join(out)


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print(render(collect(sys.argv[1])))


if __name__ == "__main__":
    main()
