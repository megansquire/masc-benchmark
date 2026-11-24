"""Task definition.

Run one pairing against one model:

    inspect eval masc_benchmark/task.py --model openrouter/meta-llama/llama-3.3-70b-instruct

Override prompt versions or any other knob with -T:

    inspect eval masc_benchmark/task.py --model openrouter/deepseek/deepseek-r1 \\
        -T reasoning_effort=medium -T reasoning_history=none -T epochs=20

Turn on prompted scratchpads for models that do not think natively:

    inspect eval masc_benchmark/task.py --model openrouter/meta-llama/llama-3.3-70b-instruct \\
        -T scammer_suffixes=scratchpad_v2 \\
        -T victim_suffixes=victim_signal_v3,scratchpad_v2 \\
        -T max_tokens=900
"""

from __future__ import annotations

import sys
from pathlib import Path

# Inspect loads task files by path, which puts this file's own directory on
# sys.path rather than the repo root - so the absolute imports below cannot find
# the package. `pip install -e .` is the real fix; this keeps things working when
# the eval is launched from an odd working directory without one.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import MemoryDataset, Sample

from masc_benchmark.prompts import load_prompt, load_rubric
from masc_benchmark.scorers import conduct, payment_gate
from masc_benchmark.solver import SEED_INSTRUCTION, scam_conversation

# Pin this. It is the one model in the benchmark that must never change, because a
# drifting grader silently rewrites your historical results.
# Pinned to one endpoint, not just one model. Without the @slug the router picks
# among Anthropic-direct, Bedrock and Vertex per request.
DEFAULT_GRADER = "openrouter/anthropic/claude-sonnet-4.5@amazon-bedrock"


@task
def masc_benchmark(
    scammer_version: str = "v1",
    victim_version: str = "vA",
    scammer_suffixes: str | None = None,
    victim_suffixes: str = "victim_signal_v3,channel_v1",
    rubric_version: str = "conduct_v6",
    scammer_model: str | None = None,
    victim_model: str | None = None,
    grader_model: str = DEFAULT_GRADER,
    max_turns: int = 16,
    temperature: float = 0.8,
    max_tokens: int = 300,
    timeout: int | None = 120,
    reasoning_effort: str | None = None,
    reasoning_history: str | None = "none",
    epochs: int = 10,
) -> Task:
    """One scammer prompt against one victim prompt, repeated `epochs` times.

    scammer_model and victim_model both default to None, meaning both roles run on
    whatever --model names. That is the 'same model plays both roles' design: it
    answers "how does this model do in this scenario" in a single sweep. Be aware
    that it confounds the two axes - if close rate rises between model generations,
    that could be a sharper seller or a softer buyer, and this configuration cannot
    tell you which. Pinning victim_model to one fixed model disentangles them, and
    is a one-line change when you want it.

    Reasoning is a TEST CONDITION, not a free observation. Native thinking is
    available on some models and not others, so a sweep that leaves it to chance is
    partly measuring "was reasoning on" rather than model capability. Set
    reasoning_effort explicitly and keep it constant across any set of runs you
    intend to compare, or run two arms and report them separately.

    reasoning_history defaults to "none" rather than Inspect's "auto" on purpose:
    "auto" resolves to different provider defaults, so across a sweep some models
    would see their own prior thinking in a sixteen-turn negotiation and others
    would not. "none" is the comparable choice. Set it to "last" or "all" if
    carrying thinking forward is the thing you want to study.
    """
    scammer = load_prompt("scammer", scammer_version, suffixes=scammer_suffixes)
    victim = load_prompt("victim", victim_version, suffixes=victim_suffixes)
    rubric = load_rubric(rubric_version)

    provenance = {**scammer.provenance(), **victim.provenance()}
    provenance.update(
        {
            "rubric_version": rubric_version,
            "grader_model": grader_model,
            "max_turns": max_turns,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "reasoning_effort": reasoning_effort,
            "reasoning_history": reasoning_history,
            "pairing": f"{scammer_version}/{victim_version}",
        }
    )

    dataset = MemoryDataset(
        [
            Sample(
                input=SEED_INSTRUCTION,
                target="payment_sent",
                id=f"{scammer_version}-{victim_version}",
                metadata=provenance,
            )
        ]
    )

    return Task(
        dataset=dataset,
        solver=scam_conversation(
            scammer_system=scammer.text,
            victim_system=victim.text,
            scammer_model=scammer_model,
            victim_model=victim_model,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
            reasoning_history=reasoning_history,
        ),
        scorer=[
            payment_gate(),
            conduct(grader_model=grader_model, rubric=rubric),
        ],
        epochs=Epochs(epochs),
        metadata=provenance,
    )
