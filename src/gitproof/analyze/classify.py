"""Classify commits (feature/fix/...) and map files to development areas."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .filters import EXT_LANG

TEST, DEVOPS, DOCS, BUILD = "Testing", "CI/DevOps", "Documentation", "Build & Config"
SECURITY, NET, ML, DB = "Security", "Networking", "ML/Data", "Database"
API, UI, PLATFORM, CORE, OTHER = "Backend/API", "UI", "Platform Integration", "Core Logic", "Other"

TEST_TOKENS = {"test", "tests", "spec", "specs", "e2e", "testing", "pytest", "jest", "cypress"}
DEVOPS_TOKENS = {"docker", "dockerfile", "terraform", "k8s", "kubernetes", "helm", "ansible",
                 "nginx", "deploy", "deployment", "workflows", "circleci", "jenkins"}
DOC_EXTS = {"md", "rst", "adoc", "txt", "mdx"}
DOC_TOKENS = {"docs", "doc", "documentation", "readme", "changelog", "license", "contributing"}
BUILD_NAMES = {
    "package.json", "pyproject.toml", "pubspec.yaml", "cargo.toml", "go.mod", "pom.xml",
    "setup.py", "setup.cfg", "makefile", "cmakelists.txt", "build.gradle", "build.gradle.kts",
    "settings.gradle", "gradle.properties", ".gitignore", ".editorconfig", "tsconfig.json",
    "analysis_options.yaml", "tox.ini", "pubspec.lock", "composer.json", "gemfile",
    "build.rs", "rust-toolchain.toml", "deno.json", ".env.example",
}
BUILD_RE = re.compile(
    r"(^|/)(requirements[^/]*\.txt|tsconfig[^/]*\.json|\.eslintrc[^/]*|\.prettierrc[^/]*|"
    r"(vite|webpack|rollup|babel|next|tailwind|postcss|jest|vitest)\.config\.[a-z]+)$")
PLATFORM_NAMES = {"androidmanifest.xml", "info.plist"}

# Ordered: the first area whose tokens appear in the path wins.
DOMAIN_TOKENS: list[tuple[str, set[str]]] = [
    (SECURITY, {"security", "auth", "authentication", "crypto", "encryption", "cipher", "ids",
                "nids", "intrusion", "detection", "malware", "vulnerability", "threat",
                "attack", "attacks", "poisoning", "firewall", "jwt", "oauth", "soc"}),
    (NET, {"net", "network", "networking", "socket", "sockets", "transport", "protocol",
           "protocols", "p2p", "peer", "peers", "discovery", "transfer", "websocket", "tcp",
           "udp", "http", "https", "grpc", "mdns", "bluetooth", "ble", "wifi", "packet",
           "packets", "lan", "rpc", "ipfs"}),
    (ML, {"ml", "model", "models", "training", "train", "notebook", "notebooks", "dataset",
          "datasets", "data", "experiment", "experiments", "inference", "embedding",
          "embeddings", "llm", "rag", "agent", "agents", "prompt", "prompts", "eval",
          "evaluation", "benchmark", "benchmarks", "drift", "reward", "policy", "rl"}),
    (DB, {"db", "database", "databases", "sql", "sqlite", "migration", "migrations", "schema",
          "schemas", "orm", "prisma", "redis", "mongo", "storage", "repository", "repositories"}),
    (API, {"api", "apis", "server", "servers", "backend", "routes", "router", "routers",
           "controller", "controllers", "handler", "handlers", "endpoint", "endpoints",
           "service", "services", "middleware", "graphql"}),
    (UI, {"ui", "ux", "view", "views", "widget", "widgets", "screen", "screens", "page",
          "pages", "component", "components", "layout", "layouts", "styles", "theme", "themes",
          "frontend", "dashboard", "cli", "tui"}),
    (PLATFORM, {"android", "ios", "windows", "macos", "linux", "platform", "platforms",
                "native", "desktop", "tauri", "electron", "runner"}),
]
UI_EXTS = {"css", "scss", "html", "htm", "vue", "svelte", "tsx", "jsx", "xib", "storyboard"}
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def path_tokens(path: str) -> set[str]:
    spaced = _CAMEL.sub(" ", path)
    return {t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t}


def _domain_rules(extra: dict[str, list[str]] | None) -> list[tuple[str, set[str]]]:
    if not extra:
        return DOMAIN_TOKENS
    rules = [(area, set(toks) | set(extra.get(area, []))) for area, toks in DOMAIN_TOKENS]
    known = {a for a, _ in DOMAIN_TOKENS}
    rules += [(a, set(t)) for a, t in extra.items() if a not in known]
    return rules


def area_for_path(path: str, extra: dict[str, list[str]] | None = None) -> str:
    low = path.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    tokens = path_tokens(path)
    if tokens & TEST_TOKENS or re.search(r"(_test|\.test|\.spec|_spec)\.[a-z0-9]+$", low):
        return TEST
    if (low.startswith((".github/", ".circleci/")) or name in {".gitlab-ci.yml", ".dockerignore"}
            or tokens & DEVOPS_TOKENS):
        return DEVOPS
    if name in BUILD_NAMES or BUILD_RE.search(low) or ext in {"toml", "gradle"}:
        return BUILD
    if name in PLATFORM_NAMES:
        return PLATFORM
    if ext in DOC_EXTS or (tokens & DOC_TOKENS and ext not in EXT_LANG):
        return DOCS
    for area, toks in _domain_rules(extra):
        if tokens & toks:
            return area
    if ext in UI_EXTS:
        return UI
    if ext == "sql":
        return DB
    if ext in EXT_LANG:
        return CORE
    return OTHER


CONVENTIONAL = {
    "feat": "feature", "feature": "feature", "fix": "fix", "bugfix": "fix", "hotfix": "fix",
    "refactor": "refactor", "test": "test", "tests": "test", "docs": "docs", "doc": "docs",
    "ci": "ci", "build": "build", "chore": "chore", "perf": "perf", "style": "style",
    "revert": "chore", "init": "init",
}
CONV_RE = re.compile(r"^(?P<t>[a-z]+)(\([^)]*\))?!?:\s", re.IGNORECASE)
KEYWORD_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("init", re.compile(r"^(initial|first) commit|^init(ial)?\b|\bscaffold|project setup|"
                        r"^create (the )?(project|repo)", re.IGNORECASE)),
    ("fix", re.compile(r"\b(fix|fixes|fixed|fixing|bug|bugfix|hotfix|patch|resolve[sd]?|crash|"
                       r"regression)\b", re.IGNORECASE)),
    ("refactor", re.compile(r"\b(refactor\w*|clean ?up|restructur\w*|reorgani[sz]\w*|rename[sd]?|"
                            r"simplif\w*|extract|move[sd]?)\b", re.IGNORECASE)),
    ("perf", re.compile(r"\b(perf\w*|optimi[sz]\w*|speed ?up|faster|cache|caching)\b", re.IGNORECASE)),
    ("docs", re.compile(r"\b(readme|docs?|documentation|changelog|typo|comments?)\b", re.IGNORECASE)),
    ("test", re.compile(r"\b(tests?|testing|specs?|coverage|pytest|unittest)\b", re.IGNORECASE)),
    ("ci", re.compile(r"\b(ci|workflows?|github actions?|pipeline|lint\w*)\b", re.IGNORECASE)),
    ("style", re.compile(r"\b(style|format\w*|prettier|whitespace)\b", re.IGNORECASE)),
    ("build", re.compile(r"\b(bump|upgrade[sd]?|dependenc\w*|deps|version|release|lockfile|"
                         r"gitignore|config(uration)?|setup)\b", re.IGNORECASE)),
    ("feature", re.compile(r"\b(add|added|adds|adding|implement\w*|create[sd]?|creating|"
                           r"introduc\w*|support\w*|new|feat\w*|enable[sd]?|integrat\w*|"
                           r"build|allow\w*)\b", re.IGNORECASE)),
]


def classify_commit(subject: str, is_merge: bool, files: Iterable[tuple[str, int, int]],
                    extra_areas: dict[str, list[str]] | None = None) -> str:
    """`files` = (path, additions, deletions) for non-noise files only."""
    if is_merge or re.match(r"^merge (branch|pull request|remote)", subject, re.IGNORECASE):
        return "merge"
    m = CONV_RE.match(subject)
    if m and m.group("t").lower() in CONVENTIONAL:
        return CONVENTIONAL[m.group("t").lower()]
    files = list(files)
    if files:
        areas = {area_for_path(p, extra_areas) for p, _, _ in files}
        if areas == {TEST}:
            return "test"
        if areas == {DOCS}:
            return "docs"
        if areas == {DEVOPS}:
            return "ci"
        if areas == {BUILD}:
            return "build"
    for kind, pattern in KEYWORD_RULES:
        if pattern.search(subject):
            return kind
    adds = sum(a for _, a, _ in files)
    dels = sum(d for _, _, d in files)
    if adds > 2 * dels and adds > 0:
        return "feature"
    if dels > 2 * adds and dels > 0:
        return "refactor"
    return "chore"


def area_weights(files: Iterable[tuple[str, int, int]],
                 extra_areas: dict[str, list[str]] | None = None) -> dict[str, int]:
    weights: dict[str, int] = {}
    for path, adds, dels in files:
        area = area_for_path(path, extra_areas)
        weights[area] = weights.get(area, 0) + adds + dels
    return weights


def primary_area(weights: dict[str, int]) -> str:
    return max(weights.items(), key=lambda kv: kv[1])[0] if weights else OTHER
