#!/usr/bin/env python3
"""Run one pairing across a list of models in a single eval_set.

    python sweep.py --check                 # preflight: who serves these models
    python sweep.py --scammer v4 --victim vB --rubric conduct_v3 --epochs 10

eval_set is the right entry point for a sweep rather than looping `inspect eval`:
it retries failed runs, skips work already completed in the same log directory, and
lands everything in one place so the models are directly comparable.

MODEL SPECS
-----------
One per line in a --models file, or the defaults below. Syntax:

    openrouter/meta-llama/llama-3.3-70b-instruct@Groq     pinned to one provider
    openrouter/openai/gpt-4o-mini                         no pin (first-party)

Pinning matters more than it looks. OpenRouter serves the same open-weight model
from several hosts at DIFFERENT QUANTIZATIONS - Llama 3.3 70B comes as fp8 from
DeepInfra, bf16 from Novita, fp16 from CoreWeave. Those are not the same system and
will not give you the same close rate. Unpinned, your epochs get scattered across
precisions and the resulting variance reads as model behaviour.

Pinned specs set allow_fallbacks=False on purpose: a hard error you can rerun beats
a silent quantization swap you cannot see in the results.

NEVER add OpenRouter's `models` argument (a fallback list of *other models*) to
this script. It would make rate-limit errors disappear and quietly ruin the
benchmark - OpenRouter would serve a different model while the log still records
the one you asked for. Provider fallback swaps the host and is safe; model
fallback swaps the model and is poison.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import date
from pathlib import Path

from inspect_ai import eval_set
from inspect_ai.model import get_model

from masc_benchmark.logdir import config_hash
from masc_benchmark.task import DEFAULT_GRADER, masc_benchmark

# Defaults chosen for availability as much as capability. mistral-small-24b was
# dropped: OpenRouter has exactly one endpoint for it (DeepInfra), so when that
# pool is saturated there is nothing to fall back to and the run just grinds.
DEFAULT_MODELS = [
    "openrouter/meta-llama/llama-3.3-70b-instruct@Groq",
    "openrouter/openai/gpt-4o-mini",
    "openrouter/anthropic/claude-3.5-haiku",
    # Two endpoints only, both flaky at time of writing - run --check first.
    "openrouter/qwen/qwen-2.5-72b-instruct@DeepInfra",
]

ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"


def parse_spec(spec: str) -> tuple[str, str | None]:
    """'openrouter/meta-llama/llama-3.3-70b@Groq' -> (model, 'Groq')."""
    if "@" in spec:
        model, provider = spec.rsplit("@", 1)
        return model.strip(), provider.strip()
    return spec.strip(), None


def read_models(path: Path | None) -> list[str]:
    if path is None:
        return DEFAULT_MODELS
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()  # drop trailing annotations
        if line:
            out.append(line)
    return out


def build_models(specs: list[str]) -> list:
    """Turn specs into Model instances, each carrying its own provider routing."""
    models = []
    for spec in specs:
        name, provider = parse_spec(spec)
        if provider:
            models.append(
                get_model(
                    name,
                    memoize=False,
                    provider={"order": [provider], "allow_fallbacks": False},
                )
            )
        else:
            models.append(get_model(name, memoize=False))
    return models


def check_models(specs: list[str]) -> None:
    """Preflight against OpenRouter's public endpoints API.

    Catches the two failure modes that cost real time: a model with a single
    endpoint (nothing to fall back to when that host is busy) and a pinned
    provider that does not actually serve the model.
    """
    print(f"{'model':<48}{'endpoints':>10}  {'pinned':<18}{'status':<14}")
    print("-" * 92)
    for spec in specs:
        name, pin = parse_spec(spec)
        bare = name.split("/", 1)[1] if name.startswith("openrouter/") else name
        try:
            with urllib.request.urlopen(
                ENDPOINTS_URL.format(model=bare), timeout=20
            ) as r:
                data = json.load(r)["data"]
            eps = data.get("endpoints") or []
        except Exception as exc:  # noqa: BLE001
            print(f"{bare:<48}{'?':>10}  {pin or '-':<18}{'lookup failed':<14}{exc}")
            continue

        names = [e.get("provider_name") for e in eps]
        tags = [e.get("tag") for e in eps]
        if pin and pin not in names and pin not in tags:
            status = "PIN MISSING"
        elif not pin and len(eps) == 1:
            status = "SINGLE-HOMED"
        else:
            status = "ok"
        print(f"{bare:<48}{len(eps):>10}  {pin or '-':<18}{status:<14}")

        # Sorted by quantization then uptime: for a benchmark the precision matters
        # more than the price, and a bare provider name can span several of them.
        # Best precision first. mxfp4 (microscaling fp4) outranks plain fp4: same
        # bit width, but a shared scale per block rather than per tensor, so it
        # degrades less. An earlier version had these two the wrong way round.
        order = {"bf16": 0, "fp16": 1, "fp8": 2, "int8": 3, "mxfp4": 4, "fp4": 5}
        eps = sorted(eps, key=lambda e: (order.get(str(e.get("quantization")), 9),
                                         -(e.get("uptime_last_1d") or 0)))
        print(f"     {'slug (put this after @)':<34}{'quant':<8}{'in $/M':>8}"
              f"{'out $/M':>9}{'up24h':>8}  status")
        for e in eps:
            pricing = e.get("pricing") or {}
            up = e.get("uptime_last_1d")
            uptime = f"{up:>6.1f}%" if isinstance(up, (int, float)) else "   n/a"
            tag = str(e.get("tag") or e.get("provider_name", ""))
            hit = pin and pin in (e.get("provider_name"), e.get("tag"))
            st = e.get("status")
            flag = "" if st == 0 else f" status={st}"
            print(
                f"     {tag:<34}{str(e.get('quantization', '?')):<8}"
                f"{float(pricing.get('prompt', 0)) * 1e6:>8.2f}"
                f"{float(pricing.get('completion', 0)) * 1e6:>9.2f}"
                f"{uptime}{flag}{'  <-- pinned' if hit else ''}"
            )
        print("     (a bare provider slug matches ALL its endpoints, including other")
        print("      quantizations. Use the full slug to pin precision.)")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--models", type=Path, default=None, help="file, one spec per line")
    ap.add_argument("--check", action="store_true",
                    help="query OpenRouter for who serves each model, then exit")
    ap.add_argument("--scammer", default="v1")
    ap.add_argument("--victim", default="vA")
    ap.add_argument("--rubric", default="conduct_v1")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--max-turns", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument(
        "--reasoning-effort", default=None,
        choices=[None, "none", "minimal", "low", "medium", "high"],
        help="pin this across a sweep; leaving it unset means thinking models "
             "think and others do not, which is a condition difference, not a result",
    )
    ap.add_argument(
        "--reasoning-history", default="none", choices=["none", "last", "all", "auto"],
        help="whether a model sees its own prior thinking; 'auto' varies by provider",
    )
    ap.add_argument("--scratchpad", action="store_true",
                    help="add prompted <thinking> scratchpads to both roles")
    ap.add_argument("--grader", default=DEFAULT_GRADER)
    ap.add_argument("--max-connections", type=int, default=4)
    ap.add_argument("--log-dir", type=Path, default=None)
    args = ap.parse_args()

    specs = read_models(args.models)

    if args.check:
        check_models(specs)
        return

    stamp = date.today().isoformat()
    suffix_tag = "_scratchpad" if args.scratchpad else ""
    effort_tag = f"_r-{args.reasoning_effort}" if args.reasoning_effort else ""

    scammer_suffixes = "channel_v1,scratchpad_v2" if args.scratchpad else "channel_v1"
    victim_suffixes = (
        "victim_signal_v3,channel_v1,scratchpad_v2" if args.scratchpad else "victim_signal_v3,channel_v1"
    )
    max_tokens = max(args.max_tokens, 900) if args.scratchpad else args.max_tokens

    # See the note in ladder.py: eval_set will not write into a directory holding
    # logs from a different task configuration, so the name must change whenever
    # the configuration does. Date and flags alone are not enough - a rubric bump
    # on the same day collides with the previous run.
    cfg = config_hash(args, extra={'victim_suffixes': victim_suffixes,
                                 'scammer_suffixes': scammer_suffixes,
                                 'max_tokens': max_tokens})
    log_dir = args.log_dir or (
        Path("logs")
        / f"{args.scammer}-{args.victim}-{args.rubric}{suffix_tag}{effort_tag}"
          f"_{stamp}_{cfg}"
    )

    print(f"pairing   : {args.scammer}/{args.victim}  rubric={args.rubric}")
    print(f"models    : {len(specs)}")
    for s in specs:
        name, pin = parse_spec(s)
        print(f"              {name}" + (f"   [pinned: {pin}]" if pin else ""))
    print(f"epochs    : {args.epochs}  (total runs: {len(specs) * args.epochs})")
    print(f"reasoning : effort={args.reasoning_effort} history={args.reasoning_history}")
    print(f"grader    : {args.grader}")
    print(f"log dir   : {log_dir}\n")

    if args.reasoning_effort is None:
        print("note: reasoning_effort unset - thinking models will think and others "
              "will not.\n      Fine for a realistic-conditions arm; not a clean "
              "capability comparison.\n")
    if args.scammer in ("v3", "v4") and (args.victim != "vB" or args.rubric != "conduct_v3"):
        print("WARNING: scammer v3/v4 need --victim vB and --rubric conduct_v3.\n"
              "         vA has no address to give and older rubrics never ask about\n"
              "         geography, so asked_for_address will read 0 for every run.\n")

    success, logs = eval_set(
        tasks=[
            masc_benchmark(
                scammer_version=args.scammer,
                victim_version=args.victim,
                scammer_suffixes=scammer_suffixes,
                victim_suffixes=victim_suffixes,
                rubric_version=args.rubric,
                grader_model=args.grader,
                max_turns=args.max_turns,
                temperature=args.temperature,
                max_tokens=max_tokens,
                reasoning_effort=args.reasoning_effort,
                reasoning_history=args.reasoning_history,
                epochs=args.epochs,
            )
        ],
        model=build_models(specs),
        log_dir=str(log_dir),
        max_connections=args.max_connections,
        retry_attempts=3,
    )

    print(f"\ncomplete: {success}  ({len(logs)} logs)")
    print(f"inspect view --log-dir {log_dir}")


if __name__ == "__main__":
    main()
