"""Loading and fingerprinting of frozen prompt files.

Every prompt used in a run is hashed and the hash goes into the eval log. That is
what makes a comparison across months meaningful: if a prompt file is edited, the
hash changes and old results stop being comparable. Nothing here mutates prompts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    """A prompt as it was actually sent, plus enough provenance to reproduce it."""

    kind: str
    version: str
    base: str
    suffixes: tuple[str, ...] = ()
    suffix_versions: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n\n".join([self.base, *self.suffixes]) if self.suffixes else self.base

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]

    @property
    def base_fingerprint(self) -> str:
        """Hash of the frozen base alone, ignoring harness scaffolding."""
        return hashlib.sha256(self.base.encode("utf-8")).hexdigest()[:12]

    def provenance(self) -> dict[str, str | None]:
        return {
            f"{self.kind}_version": self.version,
            f"{self.kind}_base_sha": self.base_fingerprint,
            f"{self.kind}_sent_sha": self.fingerprint,
            f"{self.kind}_suffixes": "+".join(self.suffix_versions) or None,
        }


def _read(path: Path) -> str:
    if not path.exists():
        available = sorted(p.stem for p in path.parent.glob("*.txt")) if path.parent.exists() else []
        raise FileNotFoundError(
            f"No prompt at {path}. Available in {path.parent.name}/: {available or 'none'}"
        )
    return path.read_text(encoding="utf-8").strip()


def _normalise(suffixes: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if suffixes is None:
        return ()
    if isinstance(suffixes, str):
        # Accept a comma-separated string so suffixes can be passed on the CLI:
        #   -T victim_suffixes=victim_signal_v1,scratchpad_v1
        return tuple(s.strip() for s in suffixes.split(",") if s.strip())
    return tuple(suffixes)


def load_prompt(
    kind: str,
    version: str,
    suffixes: str | list[str] | tuple[str, ...] | None = None,
) -> Prompt:
    """Load prompts/<kind>/<version>.txt, optionally appending harness suffixes.

    Suffixes are kept in separate files on purpose. The base prompt is the frozen
    research artifact; suffixes are scaffolding (output markers, scratchpad
    instructions) that may need to change without invalidating the benchmark.
    Keeping them apart means the base hash stays stable when scaffolding moves.

    Suffix order is preserved and affects the sent hash, so a reordering is
    visible in the logs rather than silent.
    """
    base = _read(PROMPTS_DIR / kind / f"{version}.txt")
    versions = _normalise(suffixes)
    texts = tuple(_read(PROMPTS_DIR / "suffix" / f"{v}.txt") for v in versions)
    return Prompt(
        kind=kind,
        version=version,
        base=base,
        suffixes=texts,
        suffix_versions=versions,
    )


def load_rubric(version: str) -> str:
    return _read(PROMPTS_DIR / "grader" / f"{version}.txt")
