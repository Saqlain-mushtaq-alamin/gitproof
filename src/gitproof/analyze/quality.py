"""Objective repository health signals (tests, CI, docs, releases) and a 0-100 score."""
from __future__ import annotations

import re
from typing import Any

from .classify import TEST, area_for_path
from .filters import language_for, noise_reason

LINTER_NAMES = {
    "ruff.toml", ".ruff.toml", ".pre-commit-config.yaml", ".flake8", "mypy.ini",
    "analysis_options.yaml", ".editorconfig", "rustfmt.toml", "clippy.toml", ".golangci.yml",
    ".golangci.yaml", "biome.json",
}
SECTION_RE = re.compile(
    r"^#{1,4}\s*(install\w*|usage|getting started|setup|quick ?start|how to run|build)",
    re.IGNORECASE | re.MULTILINE)


def readme_score(text: str | None) -> tuple[int, list[str]]:
    if not text:
        return 0, []
    reasons = []
    if len(text) >= 300:
        reasons.append("substantial text")
    if len(re.findall(r"^#{1,4}\s+\S", text, re.MULTILINE)) >= 3:
        reasons.append("structured headings")
    if "```" in text:
        reasons.append("code examples")
    if SECTION_RE.search(text):
        reasons.append("install/usage section")
    if re.search(r"!\[[^\]]*\]\(|<img\s", text):
        reasons.append("images/screenshots")
    return len(reasons), reasons


def _first_sentences(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 80 else cut.rstrip() + "..."


def extract_purpose(readme: str | None, description: str | None) -> str:
    """First real prose paragraph of the README, else the GitHub description."""
    if readme:
        in_code = False
        paragraph: list[str] = []
        for raw in readme.splitlines():
            line = raw.strip()
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            skip = (not line or line.startswith(("#", "!", "<", "[![", "|", ">", "-", "*", "=", "---"))
                    or re.fullmatch(r"[\W_]+", line))
            if skip:
                if paragraph:
                    break
                continue
            paragraph.append(line)
        text = " ".join(paragraph)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"[*_`]+", "", text).strip()
        if len(text.split()) >= 6:
            return _first_sentences(text, 280)
    if description:
        return description.strip()
    return "No description available."


def assess(files: list[tuple[str, int]], readme: str | None, release_count: int) -> dict[str, Any]:
    paths = [p for p, _ in files if not noise_reason(p)]
    lows = [p.lower() for p in paths]
    names = {p.rsplit("/", 1)[-1] for p in lows}
    source = [p for p in paths if language_for(p) and area_for_path(p) != TEST]
    tests = [p for p in paths if language_for(p) and area_for_path(p) == TEST]
    has_tests = bool(tests)
    test_ratio = len(tests) / max(1, len(source) + len(tests))
    has_ci = any(p.startswith((".github/workflows/", ".circleci/")) or p.endswith(".gitlab-ci.yml")
                 for p in lows)
    has_license = any("/" not in p and p.split(".")[0] in {"license", "copying", "licence"}
                      for p in lows)
    has_docker = any(n == "dockerfile" or n.startswith("docker-compose") for n in names)
    has_docs_dir = any(p.startswith(("docs/", "doc/")) for p in lows)
    has_lint = bool(names & LINTER_NAMES) or any(
        n.startswith((".eslintrc", ".prettierrc")) for n in names)
    r_score, r_reasons = readme_score(readme)

    score = r_score * 5
    score += 15 if has_tests else 0
    score += 10 if test_ratio >= 0.10 else 0
    score += 15 if has_ci else 0
    score += 10 if has_license else 0
    score += 10 if release_count >= 3 else 5 if release_count >= 1 else 0
    score += 5 * sum([has_docs_dir, has_docker, has_lint])

    badges = [f"README {r_score}/5"]
    for flag, label in [(has_tests, "Tests"), (has_ci, "CI"), (has_license, "License"),
                        (release_count > 0, f"{release_count} release(s)"),
                        (has_docker, "Docker"), (has_docs_dir, "Docs dir"),
                        (has_lint, "Lint config")]:
        if flag:
            badges.append(label)
    return {"score": min(score, 100), "readme_score": r_score, "readme_reasons": r_reasons,
            "has_tests": has_tests, "test_file_ratio": round(test_ratio, 3), "has_ci": has_ci,
            "has_license": has_license, "has_docker": has_docker, "has_docs_dir": has_docs_dir,
            "has_lint_config": has_lint, "releases": release_count, "badges": badges}
