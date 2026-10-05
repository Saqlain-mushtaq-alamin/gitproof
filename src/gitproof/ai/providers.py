"""Ollama (local, default) and Claude (cloud, opt-in) providers over plain HTTP."""
from __future__ import annotations

import os

import httpx

from .base import AIError

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_URL = "https://api.anthropic.com"
PREFERRED_LOCAL = ("qwen2.5", "qwen3", "llama3", "mistral", "gemma", "phi")


class OllamaProvider:
    name = "ollama"
    is_cloud = False

    def __init__(self, model: str | None = None, host: str | None = None,
                 transport: httpx.BaseTransport | None = None, timeout: float = 300.0):
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self._http = httpx.Client(base_url=self.host, timeout=timeout, transport=transport)
        self.model = model or self._pick_model()

    def _get(self, path: str) -> dict:
        try:
            resp = self._http.get(path)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise AIError(f"Cannot reach Ollama at {self.host}. Install it from https://ollama.com, "
                          "start it (`ollama serve`), then `ollama pull qwen2.5:7b`.") from None
        except httpx.HTTPError as exc:
            raise AIError(f"Ollama request failed: {exc}") from None

    def installed_models(self) -> list[str]:
        return [m["name"] for m in self._get("/api/tags").get("models", [])]

    def _pick_model(self) -> str:
        models = self.installed_models()
        if not models:
            raise AIError("Ollama is running but has no models. Run: ollama pull qwen2.5:7b")
        for prefix in PREFERRED_LOCAL:
            for m in models:
                if m.startswith(prefix):
                    return m
        return models[0]

    def generate(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        body = {"model": self.model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": max_tokens}}
        try:
            resp = self._http.post("/api/chat", json=body)
        except httpx.ConnectError:
            raise AIError(f"Cannot reach Ollama at {self.host}.") from None
        except httpx.HTTPError as exc:
            raise AIError(f"Ollama request failed: {exc}") from None
        if resp.status_code == 404:
            raise AIError(f"Ollama does not have model '{self.model}'. Run: ollama pull {self.model}")
        if resp.status_code >= 400:
            raise AIError(f"Ollama error {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["message"]["content"]
        except (KeyError, ValueError):
            raise AIError("unexpected reply from Ollama") from None


class ClaudeProvider:
    name = "claude"
    is_cloud = True

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None, base_url: str = ANTHROPIC_URL,
                 timeout: float = 120.0):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise AIError("No Anthropic API key. Set ANTHROPIC_API_KEY (create one at "
                          "https://console.anthropic.com). API usage is billed separately from "
                          "a claude.ai subscription.")
        self.model = model or DEFAULT_CLAUDE_MODEL
        self._http = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})

    def generate(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": 0.2,
                "system": system, "messages": [{"role": "user", "content": prompt}]}
        try:
            resp = self._http.post("/v1/messages", json=body)
        except httpx.HTTPError as exc:
            raise AIError(f"Could not reach the Anthropic API: {exc}") from None
        if resp.status_code == 401:
            raise AIError("The Anthropic API rejected the key (401). Check ANTHROPIC_API_KEY.")
        if resp.status_code == 429:
            raise AIError("Anthropic API rate limit or quota reached (429). Try again later.")
        if resp.status_code >= 400:
            try:
                detail = resp.json()["error"]["message"]
            except (KeyError, ValueError):
                detail = resp.text[:200]
            raise AIError(f"Anthropic API error {resp.status_code}: {detail}")
        try:
            return "".join(b["text"] for b in resp.json()["content"] if b.get("type") == "text")
        except (KeyError, ValueError, TypeError):
            raise AIError("unexpected reply from the Anthropic API") from None


def make_provider(name: str, model: str | None = None, host: str | None = None,
                  api_key: str | None = None, transport: httpx.BaseTransport | None = None):
    name = name.lower()
    if name == "ollama":
        return OllamaProvider(model, host, transport)
    if name == "claude":
        return ClaudeProvider(api_key, model, transport)
    raise AIError(f"Unknown provider '{name}'. Use ollama or claude.")
