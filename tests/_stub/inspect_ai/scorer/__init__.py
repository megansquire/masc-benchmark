from dataclasses import dataclass, field
from typing import Any
CORRECT="C"; INCORRECT="I"
@dataclass
class Score:
    value: Any=None; answer: Any=None; explanation: str=""; metadata: dict=field(default_factory=dict)
Scorer=Any
@dataclass
class Target: target: Any=None
def accuracy(*a,**k): return "accuracy"
def stderr(*a,**k): return "stderr"
def mean(*a,**k): return "mean"
def scorer(metrics=None):
    def deco(fn):
        def wrapper(*a,**k): return fn(*a,**k)
        wrapper.__wrapped__=fn; return wrapper
    return deco
