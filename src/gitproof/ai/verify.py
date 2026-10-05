"""Check model claims against the evidence index. Only verified claims are ever shown."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .facts import Digest, Fact, numbers_in

STOP = set(["a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be", "been", "by", "can", "did", "do", "does", "for", "from", "had", "has", "have", "he", "her", "his", "how", "in", "into", "is", "it", "its", "more", "most", "not", "of", "on", "one", "or", "other", "our", "out", "over", "she", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "up", "was", "were", "what", "when", "where", "which", "while", "who", "will", "with", "would", "you", "your", "developer", "developers", "project", "projects", "repository", "repositories", "work", "worked", "working", "code", "commit", "commits", "using", "used", "use"])


@dataclass
class Claim:
    text: str
    evidence: list[str]


@dataclass
class Dropped:
    text: str
    reason: str


def _stem(word: str) -> str:
    return word[:5]


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9+#.\-/]{2,}", text.lower())
    return {_stem(w.strip(".-/")) for w in words if w not in STOP and len(w.strip(".-/")) > 2}


def parse_claims(payload: Any) -> list[tuple[str, list[str]]]:
    """Accept the documented shape, tolerate small deviations, reject anything else."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("claims")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        ev = item.get("evidence", item.get("citations", []))
        if isinstance(ev, str):
            ev = [ev]
        if isinstance(text, str) and text.strip() and isinstance(ev, list):
            out.append((text.strip(), [str(e).strip().strip("[]") for e in ev]))
    return out


def verify_claims(raw: list[tuple[str, list[str]]], digest: Digest,
                  context_text: str | None = None) -> tuple[list[Claim], list[Dropped]]:
    """Keep a claim only if (1) it cites at least one real fact, (2) every number it states appears
    in the data it was given, and (3) it shares at least one meaningful word with what it cites."""
    allowed_numbers = numbers_in(context_text if context_text is not None else digest.text)
    kept: list[Claim] = []
    dropped: list[Dropped] = []
    for text, ids in raw:
        valid: list[Fact] = []
        for i in ids:
            fact = digest.facts.get(i)
            if fact and fact not in valid:
                valid.append(fact)
        if not valid:
            dropped.append(Dropped(text, "cites no known evidence"))
            continue
        bad = [n for n in numbers_in(text) if n not in allowed_numbers]
        if bad:
            dropped.append(Dropped(text, f"states numbers not found in the data ({', '.join(sorted(bad))})"))
            continue
        cited_vocab: set[str] = set()
        cited_numbers: set[str] = set()
        for f in valid:
            cited_vocab |= tokens(f.text) | tokens(f.id)
            cited_numbers |= numbers_in(f.text)
        # a claim is related to its evidence if they share a meaningful word, or the claim's
        # figures are the cited fact's figures ("9 commits in 1 repository" vs a totals fact)
        if not (tokens(text) & cited_vocab or numbers_in(text) & cited_numbers):
            dropped.append(Dropped(text, "shares no content with the evidence it cites"))
            continue
        kept.append(Claim(text, [f.id for f in valid]))
    return kept, dropped


def render_claims(claims: list[Claim]) -> str:
    return " ".join(c.text.rstrip() if c.text.rstrip().endswith((".", "!", "?")) else c.text.rstrip() + "."
                    for c in claims)


def evidence_refs(claims: list[Claim], digest: Digest) -> list[dict[str, str | None]]:
    seen: dict[str, dict[str, str | None]] = {}
    for c in claims:
        for i in c.evidence:
            if i not in seen:
                f = digest.facts[i]
                seen[i] = {"id": i, "kind": f.kind, "url": f.url, "label": f.text[:90]}
    return list(seen.values())
