from dataclasses import dataclass, field
from typing import Any
def task(fn): fn.__is_task__=True; return fn
class Epochs:
    def __init__(self, n, reducer=None): self.n=n; self.reducer=reducer
@dataclass
class Task:
    dataset: Any=None; solver: Any=None; scorer: Any=None
    epochs: Any=None; metadata: dict=field(default_factory=dict)
def eval_set(**kw): return True, []
