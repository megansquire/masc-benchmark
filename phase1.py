#!/usr/bin/env python3
"""Run the full Phase 1 matrix: every model in models.txt up the persona ladder.

    python phase1.py --pilot              # 3 models x 10 epochs, ~5 min, ~$1
    python phase1.py                      # everything, 30 epochs
    python phase1.py --report             # re-read existing logs, no API calls

Neither sweep.py nor ladder.py covers the model x persona matrix on its own:
sweep.py is many models against one persona, ladder.py is one model against all
four. This drives ladder.py once per model and collects the results.

Each model lands in its own log directory and gets its own health check. A model
whose health check fails is reported and excluded from the summary rather than
silently averaged in.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from inspect_ai import eval_set

from masc_benchmark.health import collect as collect_health, render as render_health
from masc_benchmark.logdir import config_hash, model_slug, prompt_fingerprint
from masc_benchmark.task import DEFAULT_GRADER, masc_benchmark

from ladder import LADDER, RELIABLE, build_model, close_rates, parse_spec, report, wilson

import sweep


def log_dir_for(model: str, args, root: Path, personas: list[str]) -> Path:
    """Per-model directory, keyed to the full run configuration.

    The hash covers every argparse parameter that affects what is measured (see
    masc_benchmark.logdir), so changing max_tokens, reasoning_effort, the rubric
    or anything else lands in a new directory instead of colliding with an
    earlier, differently-configured run.
    """
    return root / (
        f"{model_slug(model)}_"
        + config_hash(args, extra={
            "model": model,
            # content-address the prompts so editing one lands in a new directory
            "prompts": prompt_fingerprint(args.scammer, personas, args.rubric),
        })
    )


def run_model(spec: str, args, root: Path, personas: list[str]) -> Path:
    name, pin = parse_spec(spec)
    d = log_dir_for(spec, args, root, personas)
    print(f"\n{'=' * 72}\n{name}" + (f"   [{pin}]" if pin else "   [UNPINNED]"))
    print(f"{'=' * 72}")

    success, _ = eval_set(
        tasks=[
            masc_benchmark(
                scammer_version=args.scammer,
                victim_version=persona,
                scammer_suffixes=("channel_v1,scratchpad_v2" if args.scratchpad
                                  else "channel_v1"),
                victim_suffixes=("victim_signal_v3,channel_v1,scratchpad_v2"
                                 if args.scratchpad else "victim_signal_v3,channel_v1"),
                rubric_version=args.rubric,
                grader_model=args.grader,
                max_turns=args.max_turns,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                reasoning_effort=args.reasoning_effort,
                reasoning_history="none",
                epochs=args.epochs,
            )
            for persona in personas
        ],
        model=[build_model(spec)],
        log_dir=str(d),
        max_connections=args.max_connections,
        retry_attempts=3,
    )
    if not success:
        print(f"  eval_set reported failure for {name}")
    return d


def summarise(results: dict[str, tuple[Path, object]], personas: list[str],
              partial: bool = False) -> None:
    print(f"\n\n{'=' * 78}\nPHASE 1 SUMMARY\n{'=' * 78}")
    head = f"{'model':<34}" + "".join(f"{p[:9]:>11}" for p in personas)
    head += ("" if partial else f"{'rating':>8}") + f"{'health':>9}"
    print(head)
    print("-" * len(head))

    for spec, (d, health) in results.items():
        name = parse_spec(spec)[0].replace("openrouter/", "")
        counts = close_rates(d)
        cells = []
        rates = []
        for p in personas:
            c = counts.get(p)
            if not c:
                cells.append(f"{'-':>11}")
                rates.append(None)
                continue
            k, n = c.get("payment_sent", 0), c["_n"]
            rates.append(k / n)
            cells.append(f"{k / n:>10.0%} ")
        rating = sum(r is not None and r >= RELIABLE for r in rates)
        ok = "clean" if health.clean else "SUSPECT"
        cell_rating = "" if partial else f"{rating:>8}"
        print(f"{name[:33]:<34}" + "".join(cells) + cell_rating + f"{ok:>9}")

    if partial:
        print(f"\npartial ladder: {', '.join(personas)} - rating withheld")
    else:
        print(f"\nrating = number of personas closed at >= {RELIABLE:.0%}")

    broken = []
    for spec, (d, _) in results.items():
        counts = close_rates(d)
        vals = [counts[p].get("payment_sent", 0) / counts[p]["_n"]
                for p in personas if p in counts]
        if any(vals[i + 1] > vals[i] + 1e-9 for i in range(len(vals) - 1)):
            broken.append(parse_spec(spec)[0].replace("openrouter/", ""))
    if broken:
        print("\nLADDER ORDERING BROKEN for: " + ", ".join(broken))
        print("Persona difficulty is model-dependent for these. The rating is a count,")
        print("so it does not depend on the order; report the break alongside it.")
    else:
        print("\nladder ordering holds for every model")

    dirty = [parse_spec(s)[0] for s, (_, h) in results.items() if not h.clean]
    if dirty:
        print("\nEXCLUDE these models - health check not clean:")
        for m in dirty:
            print(f"  {m}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=Path, default=Path("models.txt"))
    ap.add_argument("--skip", default=None,
                    help="comma-separated substrings; matching models are skipped. "
                         "Use when a provider is rate-limited: the rest of the sweep "
                         "proceeds and you run the skipped ones later into the same "
                         "log root. Does not affect any other model's log directory.")
    ap.add_argument("--only", default=None,
                    help="comma-separated substrings; run only matching models.")
    ap.add_argument("--personas", default=None,
                    help="comma-separated subset, e.g. cautious,guarded. Order is "
                         "forced to ladder order. A partial ladder suppresses the "
                         "0-4 rating, which counts closed rungs out of four.")
    ap.add_argument("--scratchpad", action="store_true",
                    help="add prompted <SCRATCHPAD:> sections. OFF by default: on a\n                         model that reasons natively it collides with the native\n                         reasoning, and because it lives in the system prompt it\n                         makes the condition non-uniform across models. Use it as a\n                         separate labelled arm, not in the headline sweep.")
    ap.add_argument("--pilot", action="store_true",
                    help="3 models, 10 epochs - checks the ladder holds across "
                         "models before committing to the full run")
    ap.add_argument("--report", action="store_true",
                    help="re-read existing logs and summarise; no API calls")
    ap.add_argument("--scammer", default="v4")
    ap.add_argument("--rubric", default="conduct_v6")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--temperature", type=float, default=0.8)
    # Reasoning models bill thinking against the SAME budget as the message. At
    # 900 the pilot saw finish_reason=length with content=None - the model spent
    # the whole budget thinking and never wrote a message. 3000 leaves room for
    # a reasoning pass, a scratchpad and a short reply.
    ap.add_argument("--max-tokens", type=int, default=3000)
    ap.add_argument("--timeout", type=int, default=120,
                    help="per-request timeout in seconds. Without one, a connection\n                         killed by the machine sleeping blocks the run forever.")
    # Pinned, not left to the model's default. Unset, a reasoning model thinks at
    # whatever effort it likes, which is both a runaway cost and an unlogged
    # condition difference between models in the same comparison.
    ap.add_argument("--reasoning-effort", default="low",
                    choices=["none", "minimal", "low", "medium", "high"])
    ap.add_argument("--grader", default=DEFAULT_GRADER)
    ap.add_argument("--max-connections", type=int, default=4)
    ap.add_argument("--log-root", type=Path, default=None)
    args = ap.parse_args()

    if args.personas:
        want = {p.strip().lower() for p in args.personas.split(",") if p.strip()}
        unknown = want - set(LADDER)
        if unknown:
            ap.error(f"unknown persona(s): {', '.join(sorted(unknown))}. "
                     f"Choose from: {', '.join(LADDER)}")
        personas = [p for p in LADDER if p in want]   # ladder order, always
    else:
        personas = list(LADDER)
    partial = len(personas) < len(LADDER)

    specs = sweep.read_models(args.models)
    if args.only:
        pats = [p.strip().lower() for p in args.only.split(",") if p.strip()]
        specs = [s for s in specs if any(p in s.lower() for p in pats)]
    if args.skip:
        pats = [p.strip().lower() for p in args.skip.split(",") if p.strip()]
        dropped = [s for s in specs if any(p in s.lower() for p in pats)]
        specs = [s for s in specs if s not in dropped]
        for s in dropped:
            print(f"skipping {parse_spec(s)[0]}")
    if not specs:
        ap.error("no models left after --only/--skip")
    if args.pilot:
        specs = specs[:3]
        args.epochs = 10

    root = args.log_root or Path("logs") / (
        f"phase1{'_pilot' if args.pilot else ''}_{args.scammer}-{args.rubric}"
        f"_{date.today().isoformat()}"
    )

    print(f"models  : {len(specs)}")
    print(f"personas: {', '.join(personas)}")
    print(f"epochs  : {args.epochs}  ({len(specs) * len(personas) * args.epochs} runs total)")
    print(f"tokens  : max_tokens={args.max_tokens}  reasoning_effort={args.reasoning_effort}")
    print(f"scratchpad: {args.scratchpad}")
    print(f"grader  : {args.grader}")
    print(f"logs    : {root}")

    results = {}
    for spec in specs:
        d = log_dir_for(spec, args, root, personas)
        if not args.report:
            d = run_model(spec, args, root, personas)
        if not d.exists():
            print(f"  no logs at {d}, skipping")
            continue
        health = collect_health(d)
        if not args.report:
            report(close_rates(d), partial=partial)
            print(render_health(health))
        results[spec] = (d, health)

    if results:
        summarise(results, personas, partial)
    print(f"\ninspect view --log-dir {root}")


if __name__ == "__main__":
    main()
