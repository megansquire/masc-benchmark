"""One place to compute log directory names.

eval_set refuses to write into a directory holding logs from a different task
configuration, which is correct - mixing them would make the directory
uncomparable. So the directory name must change whenever the configuration does.

This has been got wrong three times by hand-listing the parameters that matter
and forgetting one: first the rubric, then max_tokens and reasoning_effort.
The fix is to stop listing. `config_hash` hashes EVERY argparse parameter except
an explicit ignore-list, so adding a new knob changes the hash automatically.
"""

from __future__ import annotations

import hashlib
from argparse import Namespace
from pathlib import Path

# Parameters that genuinely do not affect what a run measures. Everything else
# is hashed. Keep this list short and justify additions.
NOT_PART_OF_IDENTITY = {
    "log_dir",       # where results go, not what they are
    "log_root",
    "report",        # read-only mode
    "check",         # preflight mode
    "models",        # path to the list; the model itself is hashed separately
    "model",         # hashed explicitly by callers, per-model
    "skip",          # which models run does not change what a run measures,
    "only",          # so filtering must not move anyone else's directory
    "max_connections",  # concurrency
    "pilot",         # changes epochs and model count, both captured elsewhere
}


def config_hash(args: Namespace | dict, *, extra: dict | None = None,
                ignore: set[str] | None = None) -> str:
    """Short stable hash over every config value that affects task identity."""
    parts = dict(vars(args) if isinstance(args, Namespace) else args)
    for key in (ignore or NOT_PART_OF_IDENTITY):
        parts.pop(key, None)
    if extra:
        parts.update(extra)
    sig = "|".join(f"{k}={parts[k]!r}" for k in sorted(parts))
    return hashlib.sha256(sig.encode()).hexdigest()[:6]


def prompt_fingerprint(scammer: str, victims: list[str], rubric: str) -> str:
    """Hash of the actual prompt TEXT, not just the version names.

    Version names are stable across edits, so without this an edited persona file
    reuses the previous run's directory and eval_set refuses. Content-addressing
    the prompts means any edit lands somewhere new automatically.
    """
    from masc_benchmark.prompts import load_prompt, load_rubric

    parts = [load_prompt("scammer", scammer).base_fingerprint]
    parts += [f"{v}:{load_prompt('victim', v).base_fingerprint}" for v in sorted(victims)]
    parts.append(hashlib.sha256(load_rubric(rubric).encode()).hexdigest()[:12])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:8]


def model_slug(spec: str) -> str:
    """Filesystem-safe name for a model spec, pin included."""
    return (
        spec.replace("openrouter/", "")
        .replace("/", "_")
        .replace("@", "__at__")
        .replace(":", "_")
    )
