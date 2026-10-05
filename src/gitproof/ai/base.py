"""Provider interface shared by the local (Ollama) and cloud (Claude) backends."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol


class AIError(Exception):
    """Anything that stops an AI request: server down, bad key, invalid reply."""


class Provider(Protocol):
    name: str
    model: str
    is_cloud: bool

    def generate(self, system: str, prompt: str, max_tokens: int = 1200) -> str: ...


@dataclass
class ProviderInfo:
    name: str
    model: str
    is_cloud: bool


def estimate_tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token); good enough for a size warning."""
    return max(1, len(text) // 4)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Parse a JSON object from a model reply, tolerating code fences and surrounding prose."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        in_str = esc = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start:i + 1])
                    except ValueError:
                        break
        start = cleaned.find("{", start + 1)
    raise AIError("the model did not return valid JSON")
