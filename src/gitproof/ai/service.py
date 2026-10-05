"""Optional AI features: repository/profile summaries and grounded question answering."""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any

from ..db import Store
from ..util import iso, now
from . import prompts
from .base import AIError, Provider, estimate_tokens, extract_json
from .facts import Digest, Fact, clean, profile_facts, repo_digest
from .verify import STOP, evidence_refs, parse_claims, render_claims, tokens, verify_claims

NO_EVIDENCE = "No evidence found in the analyzed GitHub data to answer that."
# words that make a question sound specific without naming anything searchable
QUESTION_FILLER = set(["done", "did", "make", "made", "tell", "show", "give", "list", "describe", "summary", "summarize", "overall", "main", "major", "thing", "things", "know", "like", "many", "much", "long", "really", "actually", "currently", "ever", "person", "someone", "guy", "person", "account", "profile", "github", "tell", "me", "about"])

MAX_PROFILE_REPOS = 8


# ---------------------------------------------------------------------------------------
# calling the model
# ---------------------------------------------------------------------------------------
def _ask_model(provider: Provider, system: str, prompt: str, digest: Digest,
               context_text: str | None = None) -> dict[str, Any]:
    """One model call (with one repair retry), verified. Returns a JSON-serialisable result."""
    reply = provider.generate(system, prompt)
    try:
        payload = extract_json(reply)
    except AIError:
        reply = provider.generate(system, prompt + "\n\n" + prompts.REPAIR)
        payload = extract_json(reply)
    raw = parse_claims(payload)
    kept, dropped = verify_claims(raw, digest, context_text)
    return {
        "text": render_claims(kept),
        "claims": [{"text": c.text, "evidence": c.evidence} for c in kept],
        "evidence": evidence_refs(kept, digest),
        "dropped": [{"text": d.text, "reason": d.reason} for d in dropped],
        "proposed": len(raw),
        "provider": provider.name, "model": provider.model,
        "generated_at": iso(now()),
    }


def _hash(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------------------
def repo_input(repo: dict[str, Any]) -> tuple[Digest, str]:
    digest = repo_digest(repo)
    return digest, prompts.repo_prompt(digest.text)


def summarize_repo(store: Store, repo: dict[str, Any], provider: Provider,
                   refresh: bool = False) -> dict[str, Any]:
    digest, prompt = repo_input(repo)
    key = f"repo:{repo['full_name']}"
    ihash = _hash(prompt, provider.name, provider.model)
    cached = store.get_analysis("ai", key)
    if cached and cached.get("input_hash") == ihash and not refresh:
        return {**cached, "cached": True}
    result = _ask_model(provider, prompts.SYSTEM_REPO, prompt, digest)
    result["input_hash"] = ihash
    store.put_analysis("ai", key, result)
    return {**result, "cached": False}


def _profile_inputs(data, repo_results: dict[str, dict[str, Any]]) -> tuple[Digest, str]:
    pdig = profile_facts(data.profile)
    repo_claims = []
    top = data.repos[:MAX_PROFILE_REPOS]
    for r in top:
        res = repo_results.get(r["full_name"])
        if not res or not res.get("text"):
            continue
        rd = repo_digest(r)
        for fid, fact in rd.facts.items():
            pdig.facts.setdefault(fid, fact)
        repo_claims.append((r["name"], res["text"], [c for cl in res["claims"] for c in cl["evidence"]][:6]))
    text = pdig.text + "\n" + "\n".join(
        f"[{fid}] {f.text}" for fid, f in pdig.facts.items() if fid.startswith(("repo:", "area:", "phase:")))
    full = Digest(text=text, facts=pdig.facts)
    return full, prompts.profile_prompt(full.text, repo_claims)


def summarize_profile(store: Store, data, provider: Provider, repo_results: dict[str, dict[str, Any]],
                      refresh: bool = False) -> dict[str, Any]:
    digest, prompt = _profile_inputs(data, repo_results)
    ihash = _hash(prompt, provider.name, provider.model)
    cached = store.get_analysis("ai", "profile")
    if cached and cached.get("input_hash") == ihash and not refresh:
        return {**cached, "cached": True}
    result = _ask_model(provider, prompts.SYSTEM_PROFILE, prompt, digest)
    result["input_hash"] = ihash
    store.put_analysis("ai", "profile", result)
    return {**result, "cached": False}


def estimate_summary_tokens(data, repos: list[dict[str, Any]], include_profile: bool) -> int:
    total = sum(estimate_tokens(repo_input(r)[1]) + 350 for r in repos)
    if include_profile:
        total += estimate_tokens(profile_facts(data.profile).text) + 800 + 120 * min(len(repos), MAX_PROFILE_REPOS)
    return total


def load_ai(store: Store, data) -> dict[str, Any]:
    """Stored AI output that is still valid for the current analysis (stale entries are skipped)."""
    stored = store.all_analysis("ai")
    out: dict[str, Any] = {"profile": None, "repos": {}, "stale": []}
    for r in data.repos:
        res = stored.get(f"repo:{r['full_name']}")
        if not res:
            continue
        digest, prompt = repo_input(r)
        if res.get("input_hash") == _hash(prompt, res.get("provider", ""), res.get("model", "")):
            out["repos"][r["full_name"]] = res
        else:
            out["stale"].append(r["name"])
    prof = stored.get("profile")
    if prof:
        _, prompt = _profile_inputs(data, out["repos"])
        if prof.get("input_hash") == _hash(prompt, prof.get("provider", ""), prof.get("model", "")):
            out["profile"] = prof
        else:
            out["stale"].append("profile")
    return out


# ---------------------------------------------------------------------------------------
# question answering
# ---------------------------------------------------------------------------------------
def build_corpus(data, store: Store) -> dict[str, Fact]:
    corpus: dict[str, Fact] = dict(profile_facts(data.profile).facts)
    for r in data.repos:
        corpus.update(repo_digest(r).facts)
        url = r["url"]
        for c in store.commits(r["full_name"], user_only=True):
            if c["is_merge"]:
                continue
            fid = f"c:{c['sha'][:7]}"
            if fid in corpus and not corpus[fid].url.endswith(c["sha"]):
                fid = f"c:{c['sha'][:12]}"
            corpus.setdefault(fid, Fact(
                fid, "commit", f"{c['authored_at'][:10]} {clean(c['subject'], 120)} [{r['name']}]",
                f"{url}/commit/{c['sha']}", r["full_name"]))
        for p in store.items("pr"):
            if p["repo"] == r["full_name"]:
                fid = f"pr:{p['repo']}#{p['number']}"
                corpus.setdefault(fid, Fact(fid, "pr", f"Pull request #{p['number']} "
                                            f"{clean(p['title'], 120)}" + (" (merged)" if p["merged"] else ""),
                                            p["url"], p["repo"]))
    for p in store.items("pr"):
        if p["external"]:
            fid = f"pr:{p['repo']}#{p['number']}"
            corpus.setdefault(fid, Fact(fid, "pr", f"Pull request to {p['repo']} #{p['number']} "
                                        f"{clean(p['title'], 120)}" + (" (merged)" if p["merged"] else " (not merged)"),
                                        p["url"], p["repo"]))
    return corpus


def retrieve(question: str, corpus: dict[str, Fact], data, k: int = 24) -> tuple[Digest, int]:
    """Keyword retrieval (TF-IDF style). Returns the evidence digest and the number of real hits.
    A question with no usable keywords gets the profile overview instead; a question whose
    keywords match nothing gets no evidence at all."""
    q = {t for t in tokens(question) if t not in {w[:5] for w in QUESTION_FILLER | STOP}}
    docs = {fid: tokens(f.text + " " + fid) for fid, f in corpus.items()}
    if not q:
        chosen = [fid for fid in corpus if fid.startswith(("profile:", "skill:", "repo:"))][:k]
        hits = len(chosen)
    else:
        df = Counter(t for d in docs.values() for t in d)
        n = len(docs) or 1
        scored = []
        for fid, d in docs.items():
            overlap = q & d
            if overlap:
                scored.append((sum(math.log(1 + n / df[t]) for t in overlap), fid))
        scored.sort(key=lambda s: (-s[0], s[1]))
        chosen = [fid for _, fid in scored[:k]]
        hits = len(chosen)
        if chosen:   # give the model the account overview as context, but it does not count as a hit
            for fid in corpus:
                if fid == "profile:totals" and fid not in chosen:
                    chosen.append(fid)
    facts = {fid: corpus[fid] for fid in chosen}
    text = "\n".join(f"[{fid}] {f.text}" for fid, f in facts.items())
    return Digest(text=text, facts=facts), hits


def answer_question(store: Store, data, provider: Provider | None, question: str,
                    corpus: dict[str, Fact] | None = None) -> dict[str, Any]:
    corpus = corpus or build_corpus(data, store)
    digest, hits = retrieve(question, corpus, data)
    base = {"question": question, "hits": hits}
    if hits == 0:
        return {**base, "answer": NO_EVIDENCE, "claims": [], "evidence": [], "dropped": [],
                "grounded": False, "asked_model": False}
    if provider is None:
        raise AIError("a provider is required")
    res = _ask_model(provider, prompts.SYSTEM_ASK, prompts.ask_prompt(clean(question, 400), digest.text),
                     digest)
    grounded = bool(res["claims"])
    return {**base, **res, "answer": res["text"] if grounded else NO_EVIDENCE,
            "grounded": grounded, "asked_model": True}


def ask_payload_preview(question: str, corpus: dict[str, Fact], data) -> tuple[str, int]:
    """What would be sent for this question (used for the cloud consent screen)."""
    digest, hits = retrieve(question, corpus, data)
    prompt = prompts.ask_prompt(clean(question, 400), digest.text)
    return prompt, hits
