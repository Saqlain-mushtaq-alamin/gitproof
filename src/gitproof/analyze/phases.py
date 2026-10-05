"""Split a repository's history (for one author) into development phases.

Deterministic: split at unusually long gaps, fold tiny bursts into neighbours, and if the
history is one continuous stretch split it into equal-volume chunks. Each phase is labelled
from its mix of commit types and development areas.
"""
from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from ..util import iso

MIN_PHASE_COMMITS = 3
MAX_PHASES = 6


def _split_on_gaps(commits: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    gaps = [(commits[i + 1]["date"] - commits[i]["date"]).total_seconds() / 86400
            for i in range(len(commits) - 1)]
    positive = [g for g in gaps if g > 0.05]
    median = statistics.median(positive) if positive else 1.0
    threshold = min(90.0, max(14.0, 3 * median))
    segments: list[list[dict[str, Any]]] = [[commits[0]]]
    for gap, commit in zip(gaps, commits[1:], strict=False):
        if gap > threshold:
            segments.append([commit])
        else:
            segments[-1].append(commit)
    return segments


def _fold_small(segments: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    changed = True
    while len(segments) > 1 and changed:
        changed = False
        for i, seg in enumerate(segments):
            if len(seg) < MIN_PHASE_COMMITS:
                if i > 0:
                    segments[i - 1] = segments[i - 1] + seg
                else:
                    segments[1] = seg + segments[1]
                del segments[i]
                changed = True
                break
    return segments


def _split_even(commits: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    n = len(commits)
    if n < 8 or (commits[-1]["date"] - commits[0]["date"]).days < 14:
        return [commits]
    parts = 2 if n < 20 else 3 if n < 60 else 4
    size = n / parts
    return [commits[round(i * size): round((i + 1) * size)] for i in range(parts)]


def _merge_smallest(segments: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    while len(segments) > MAX_PHASES:
        i = min(range(len(segments) - 1), key=lambda k: len(segments[k]) + len(segments[k + 1]))
        segments[i] = segments[i] + segments[i + 1]
        del segments[i + 1]
    return segments


def _label(idx: int, total: int, types: Counter[str], areas: Counter[str], early_init: bool) -> str:
    n = sum(types.values()) or 1

    def share(*kinds: str) -> float:
        return sum(types[k] for k in kinds) / n

    if idx == 0 and (early_init or share("init", "build", "chore") >= 0.5):
        theme = "Project setup & foundations"
    elif idx == total - 1 and idx > 0 and share("docs", "ci", "style", "build") >= 0.35:
        theme = "Polish, documentation & release prep"
    elif share("feature") >= 0.4:
        theme = "Feature development"
    elif share("fix", "refactor", "perf") >= 0.4:
        theme = "Stabilization & refactoring"
    elif share("test", "docs", "ci") >= 0.4:
        theme = "Testing, documentation & tooling"
    else:
        theme = "Mixed development"
    focus = [a for a, _ in areas.most_common(3) if a not in {"Other", "Build & Config"}][:2]
    return f"{theme} - {', '.join(focus)}" if focus else theme


def build_phases(commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`commits`: dicts with date (aware datetime), type, area, lines, sha, subject."""
    commits = sorted((c for c in commits if c["type"] != "merge"), key=lambda c: c["date"])
    if not commits:
        return []
    segments = _fold_small(_split_on_gaps(commits))
    if len(segments) == 1:
        segments = _split_even(segments[0])
    segments = _merge_smallest(segments)
    phases = []
    for idx, seg in enumerate(segments):
        types = Counter(c["type"] for c in seg)
        areas: Counter[str] = Counter()
        for c in seg:
            areas[c["area"]] += max(c["lines"], 1)
        early_init = idx == 0 and any(c["type"] == "init" for c in seg[:5])
        top_areas = [a for a, _ in areas.most_common(3)]
        dominant = types.most_common(1)[0][0]
        phases.append({
            "index": idx + 1,
            "label": _label(idx, len(segments), types, areas, early_init),
            "start": iso(seg[0]["date"]), "end": iso(seg[-1]["date"]),
            "commits": len(seg), "lines": sum(c["lines"] for c in seg),
            "types": dict(types), "top_areas": top_areas,
            "summary": f"{len(seg)} commits, mostly {dominant} work"
                       + (f" in {', '.join(top_areas[:2])}" if top_areas else ""),
            "first_sha": seg[0]["sha"], "last_sha": seg[-1]["sha"],
        })
    return phases
