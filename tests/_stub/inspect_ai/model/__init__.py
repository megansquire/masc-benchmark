from dataclasses import dataclass, field
from typing import Any
@dataclass
class ChatMessage: content: Any=""; role: str="user"
class ChatMessageSystem(ChatMessage):
    def __init__(self, content): super().__init__(content, "system")
class ChatMessageUser(ChatMessage):
    def __init__(self, content): super().__init__(content, "user")
class ChatMessageAssistant(ChatMessage):
    def __init__(self, content): super().__init__(content, "assistant")
class GenerateConfig:
    def __init__(self, **kw): self.__dict__.update(kw)
    def __repr__(self): return f"GenerateConfig({self.__dict__})"
@dataclass
class ContentText: text: str=""
@dataclass
class ContentReasoning: reasoning: str=""
@dataclass
class ModelOutput:
    completion: str=""
    message: Any=None
class Model:
    def __init__(self, name="stub"): self.name=name
    async def generate(self, messages, config=None): return ModelOutput("stub reply")
_REGISTRY={}
def register_model(spec, model): _REGISTRY[spec]=model
def get_model(spec=None, **kw):
    m = _REGISTRY.get(spec or "__default__")
    if m is None:
        m = Model(spec or "stub")
    m.model_args = kw          # so tests can assert provider pinning
    return m
