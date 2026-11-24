from dataclasses import dataclass, field
from typing import Any
@dataclass
class Sample:
    input: Any=None; target: Any=None; id: Any=None; metadata: dict=field(default_factory=dict)
class MemoryDataset(list):
    def __init__(self, samples): super().__init__(samples)
