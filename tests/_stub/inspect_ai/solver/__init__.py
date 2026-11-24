from dataclasses import dataclass, field
from typing import Any
def solver(fn):
    def wrapper(*a, **k): return fn(*a, **k)
    wrapper.__wrapped__=fn; return wrapper
Solver=Any; Generate=Any
@dataclass
class TaskState:
    messages: list=field(default_factory=list)
    output: Any=None
    metadata: dict=field(default_factory=dict)
