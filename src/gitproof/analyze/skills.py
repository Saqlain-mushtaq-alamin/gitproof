"""Detect technologies and tie each one to evidence (commits the user actually made).

  * languages / tools: the user changed files of that kind            -> "strong"
  * frameworks: listed in a dependency manifest the user edited       -> "inferred"
    (we know it is a dependency at HEAD and the user touched the manifest, not which commit
    added it, so first-seen dates are approximate)
"""
from __future__ import annotations

import json
import re
import tomllib
from datetime import datetime
from typing import Any

from ..util import iso
from .filters import language_for, noise_reason

MANIFEST_NAMES = {"package.json", "pyproject.toml", "cargo.toml", "pubspec.yaml", "go.mod",
                  "pom.xml", "build.gradle", "build.gradle.kts"}
MANIFEST_RE = re.compile(r"(^|/)requirements[^/]*\.txt$")

TECH_MAP: dict[str, tuple[str, str]] = {
    "react": ("React", "Framework"), "react-dom": ("React", "Framework"),
    "react-native": ("React Native", "Framework"), "expo": ("Expo", "Framework"),
    "next": ("Next.js", "Framework"), "vue": ("Vue", "Framework"),
    "svelte": ("Svelte", "Framework"), "@angular/core": ("Angular", "Framework"),
    "express": ("Express", "Framework"), "vite": ("Vite", "Tool"),
    "tailwindcss": ("Tailwind CSS", "Framework"), "redux": ("Redux", "Library"),
    "zustand": ("Zustand", "Library"), "electron": ("Electron", "Framework"),
    "@tauri-apps/api": ("Tauri", "Framework"), "tauri": ("Tauri", "Framework"),
    "jest": ("Jest", "Testing"), "vitest": ("Vitest", "Testing"),
    "fastapi": ("FastAPI", "Framework"), "flask": ("Flask", "Framework"),
    "django": ("Django", "Framework"), "pydantic": ("Pydantic", "Library"),
    "sqlalchemy": ("SQLAlchemy", "Library"), "httpx": ("httpx", "Library"),
    "typer": ("Typer", "Library"), "rich": ("Rich", "Library"), "pytest": ("pytest", "Testing"),
    "streamlit": ("Streamlit", "Framework"), "gradio": ("Gradio", "Framework"),
    "torch": ("PyTorch", "ML/AI"), "pytorch": ("PyTorch", "ML/AI"),
    "tensorflow": ("TensorFlow", "ML/AI"), "keras": ("Keras", "ML/AI"),
    "transformers": ("Hugging Face Transformers", "ML/AI"), "numpy": ("NumPy", "ML/AI"),
    "pandas": ("pandas", "ML/AI"), "scikit-learn": ("scikit-learn", "ML/AI"),
    "sklearn": ("scikit-learn", "ML/AI"), "xgboost": ("XGBoost", "ML/AI"),
    "lightgbm": ("LightGBM", "ML/AI"), "langchain": ("LangChain", "ML/AI"),
    "openai": ("OpenAI API", "ML/AI"), "anthropic": ("Anthropic API", "ML/AI"),
    "ollama": ("Ollama", "ML/AI"), "llama-cpp-python": ("llama.cpp", "ML/AI"),
    "sentence-transformers": ("Sentence Transformers", "ML/AI"),
    "faiss-cpu": ("FAISS", "ML/AI"), "chromadb": ("ChromaDB", "ML/AI"),
    "gymnasium": ("Gymnasium", "ML/AI"), "gym": ("Gym", "ML/AI"),
    "stable-baselines3": ("Stable-Baselines3", "ML/AI"), "opencv-python": ("OpenCV", "ML/AI"),
    "shap": ("SHAP", "ML/AI"), "lime": ("LIME", "ML/AI"), "scapy": ("Scapy", "Security"),
    "peft": ("PEFT", "ML/AI"), "bitsandbytes": ("bitsandbytes", "ML/AI"),
    "vllm": ("vLLM", "ML/AI"), "onnxruntime": ("ONNX Runtime", "ML/AI"),
    "tokio": ("Tokio", "Library"), "axum": ("Axum", "Framework"),
    "actix-web": ("Actix Web", "Framework"), "serde": ("Serde", "Library"),
    "clap": ("clap", "Library"), "candle-core": ("Candle", "ML/AI"),
    "flutter": ("Flutter", "Framework"), "firebase_core": ("Firebase", "Platform"),
    "riverpod": ("Riverpod", "Library"), "flutter_riverpod": ("Riverpod", "Library"),
    "dio": ("Dio", "Library"), "firebase": ("Firebase", "Platform"),
    "github.com/gin-gonic/gin": ("Gin", "Framework"),
    "spring-boot-starter-web": ("Spring Boot", "Framework"),
    "spring-boot-starter": ("Spring Boot", "Framework"),
}

TOOL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Docker", re.compile(r"(^|/)(dockerfile[^/]*|docker-compose[^/]*\.ya?ml|\.dockerignore)$", re.IGNORECASE)),
    ("GitHub Actions", re.compile(r"^\.github/workflows/", re.IGNORECASE)),
    ("GitLab CI", re.compile(r"(^|/)\.gitlab-ci\.yml$", re.IGNORECASE)),
    ("Terraform", re.compile(r"\.tf$", re.IGNORECASE)),
    ("CMake", re.compile(r"(^|/)cmakelists\.txt$", re.IGNORECASE)),
    ("Make", re.compile(r"(^|/)makefile$", re.IGNORECASE)),
    ("Kubernetes/Helm", re.compile(r"(^|/)(k8s|kubernetes|helm)/", re.IGNORECASE)),
]


def is_manifest(path: str) -> bool:
    if noise_reason(path):
        return False
    low = path.lower()
    return low.rsplit("/", 1)[-1] in MANIFEST_NAMES or bool(MANIFEST_RE.search(low))


def _norm(name: str) -> str:
    return name.strip().lower()


def _req_name(spec: str) -> str:
    return _norm(re.split(r"[<>=!~;\[ @]", spec.strip(), maxsplit=1)[0]).replace("_", "-")


def parse_package_json(text: str) -> set[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return set()
    out: set[str] = set()
    if isinstance(data, dict):
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(data.get(key), dict):
                out.update(_norm(k) for k in data[key])
    return out


def parse_requirements(text: str) -> set[str]:
    out: set[str] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        name = _req_name(line)
        if name:
            out.add(name)
    return out


def parse_pyproject(text: str) -> set[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    out: set[str] = set()
    project = data.get("project", {})
    out.update(_req_name(s) for s in project.get("dependencies", []) if isinstance(s, str))
    for group in project.get("optional-dependencies", {}).values():
        out.update(_req_name(s) for s in group if isinstance(s, str))
    for group in data.get("dependency-groups", {}).values():
        out.update(_req_name(s) for s in group if isinstance(s, str))
    out.update(_norm(k).replace("_", "-") for k in data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
    out.discard("python")
    return out


def parse_cargo(text: str) -> set[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    out: set[str] = set()
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        out.update(_norm(k) for k in data.get(key, {}))
    out.update(_norm(k) for k in data.get("workspace", {}).get("dependencies", {}))
    return out


def parse_pubspec(text: str) -> set[str]:
    out: set[str] = set()
    section = False
    for line in text.splitlines():
        if re.match(r"^(dependencies|dev_dependencies):\s*$", line):
            section = True
        elif re.match(r"^\S", line):
            section = False
        elif section:
            m = re.match(r"^  ([A-Za-z0-9_]+):", line)
            if m:
                out.add(_norm(m.group(1)))
    return out


def parse_go_mod(text: str) -> set[str]:
    return {_norm(m) for m in re.findall(r"^\s*(?:require\s+)?([\w.\-]+\.[\w.\-/]+)\s+v\d", text, re.MULTILINE)}


def parse_gradle_or_pom(text: str) -> set[str]:
    out = {_norm(m.split(":")[1]) for m in
           re.findall(r"[\"']([\w.\-]+:[\w.\-]+)(?::[^\"']*)?[\"']", text)}
    out.update(_norm(m) for m in re.findall(r"<artifactId>([^<]+)</artifactId>", text))
    return out


def parse_manifest(path: str, text: str) -> set[str]:
    name = path.lower().rsplit("/", 1)[-1]
    if name == "package.json":
        return parse_package_json(text)
    if name == "pyproject.toml":
        return parse_pyproject(text)
    if name == "cargo.toml":
        return parse_cargo(text)
    if name == "pubspec.yaml":
        return parse_pubspec(text)
    if name == "go.mod":
        return parse_go_mod(text)
    if name in {"build.gradle", "build.gradle.kts", "pom.xml"}:
        return parse_gradle_or_pom(text)
    if MANIFEST_RE.search(path.lower()):
        return parse_requirements(text)
    return set()


def detect_frameworks(manifests: dict[str, str]) -> dict[str, dict[str, Any]]:
    techs: dict[str, dict[str, Any]] = {}
    for path, text in manifests.items():
        for dep in parse_manifest(path, text):
            hit = TECH_MAP.get(dep) or TECH_MAP.get(dep.replace("-", "_"))
            if hit:
                entry = techs.setdefault(hit[0], {"category": hit[1], "manifests": []})
                if path not in entry["manifests"]:
                    entry["manifests"].append(path)
    return techs


def repo_skills(touches: list[tuple[str, datetime, str, int]],
                frameworks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """touches: (sha, date, path, additions) for every file the user changed in this repo."""
    buckets: dict[str, dict[str, Any]] = {}

    def record(name: str, category: str, confidence: str, sha: str, date: datetime, lines: int):
        b = buckets.setdefault(name, {"name": name, "category": category, "confidence": confidence,
                                      "shas": {}, "first": date, "last": date, "lines": 0})
        b["shas"].setdefault(sha, date)
        b["first"], b["last"] = min(b["first"], date), max(b["last"], date)
        b["lines"] += lines

    manifest_index: dict[str, list[str]] = {}
    for tech, info in frameworks.items():
        for mp in info["manifests"]:
            manifest_index.setdefault(mp, []).append(tech)

    for sha, date, path, adds in touches:
        if noise_reason(path) is None:
            lang = language_for(path)
            if lang:
                record(lang, "Language", "strong", sha, date, adds)
        for tool, pattern in TOOL_PATTERNS:
            if pattern.search(path):
                record(tool, "Tool/Infra", "strong", sha, date, adds)
        for tech in manifest_index.get(path, []):
            record(tech, frameworks[tech]["category"], "inferred", sha, date, 0)

    out = []
    for b in buckets.values():
        ordered = sorted(b["shas"].items(), key=lambda kv: kv[1])
        out.append({"name": b["name"], "category": b["category"], "confidence": b["confidence"],
                    "first_seen": iso(b["first"]), "last_seen": iso(b["last"]),
                    "commits": len(ordered), "lines": b["lines"],
                    "evidence": [sha for sha, _ in ordered[:3]]})
    out.sort(key=lambda s: (-s["commits"], s["name"]))
    return out


def merge_skills(per_repo: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for repo, skills in per_repo.items():
        for s in skills:
            m = merged.setdefault(s["name"], {
                "name": s["name"], "category": s["category"], "confidence": s["confidence"],
                "first_seen": s["first_seen"], "last_seen": s["last_seen"],
                "commits": 0, "lines": 0, "repos": [], "evidence": []})
            if s["confidence"] == "strong":
                m["confidence"] = "strong"
            m["first_seen"] = min(m["first_seen"], s["first_seen"])
            m["last_seen"] = max(m["last_seen"], s["last_seen"])
            m["commits"] += s["commits"]
            m["lines"] += s["lines"]
            m["repos"].append(repo)
            m["evidence"].extend({"repo": repo, "sha": sha} for sha in s["evidence"][:2])
    result = list(merged.values())
    for m in result:
        m["evidence"] = m["evidence"][:4]
    result.sort(key=lambda s: (-s["commits"], s["name"]))
    return result
