from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def home_dir() -> Path:
    env = os.environ.get("GITPROOF_HOME")
    path = Path(env).expanduser() if env else Path.home() / ".gitproof"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return home_dir() / "config.toml"


@dataclass
class Config:
    """User configuration stored in ~/.gitproof/config.toml."""

    token: str | None = None
    aliases: list[str] = field(default_factory=list)
    last_user: str | None = None
    max_repo_size_mb: int = 300
    max_commits_per_repo: int = 50_000
    blame_max_files: int = 400
    area_tokens: dict[str, list[str]] = field(default_factory=dict)
    ai_provider: str = "ollama"
    ai_model: str | None = None
    ollama_host: str | None = None
    claude_model: str | None = None
    claude_consent: bool = False

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        cfg = cls()
        if not path.exists():
            return cfg
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return cfg
        for key in ("token", "last_user", "ai_provider", "ai_model", "ollama_host", "claude_model"):
            if isinstance(data.get(key), str):
                setattr(cfg, key, data[key])
        for key in ("max_repo_size_mb", "max_commits_per_repo", "blame_max_files"):
            if isinstance(data.get(key), int):
                setattr(cfg, key, data[key])
        if isinstance(data.get("claude_consent"), bool):
            cfg.claude_consent = data["claude_consent"]
        if isinstance(data.get("aliases"), list):
            cfg.aliases = [str(a) for a in data["aliases"]]
        tokens = data.get("area_tokens")
        if isinstance(tokens, dict):
            cfg.area_tokens = {str(k): [str(x).lower() for x in v]
                               for k, v in tokens.items() if isinstance(v, list)}
        return cfg

    def save(self) -> None:
        lines = ["# gitproof configuration"]
        if self.token:
            lines.append(f"token = {json.dumps(self.token)}")
        if self.last_user:
            lines.append(f"last_user = {json.dumps(self.last_user)}")
        lines.append(f"aliases = {json.dumps(self.aliases)}")
        lines.append(f"max_repo_size_mb = {self.max_repo_size_mb}")
        lines.append(f"max_commits_per_repo = {self.max_commits_per_repo}")
        lines.append(f"blame_max_files = {self.blame_max_files}")
        lines.append(f"ai_provider = {json.dumps(self.ai_provider)}")
        for key in ("ai_model", "ollama_host", "claude_model"):
            if getattr(self, key):
                lines.append(f"{key} = {json.dumps(getattr(self, key))}")
        lines.append(f"claude_consent = {'true' if self.claude_consent else 'false'}")
        if self.area_tokens:
            lines += ["", "[area_tokens]"]
            for area, toks in self.area_tokens.items():
                lines.append(f"{json.dumps(area)} = {json.dumps(toks)}")
        path = config_path()
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass


def resolve_token(cli_token: str | None, cfg: Config) -> str | None:
    return cli_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or cfg.token
