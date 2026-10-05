# gitproof

Turn a GitHub username into an **evidence-backed developer profile and proof-of-work report**.
Free, local-first, runs in your terminal.

- Reads the full history (commits, PRs, issues, releases) and mines the git repositories themselves.
- Counts only what the developer wrote: aliases/noreply emails, noise filtered (lockfiles, vendored,
  generated, bulk imports), "surviving lines" via `git blame`.
- Terminal dashboard, plus export to **Markdown, JSON, HTML and PDF** (full report or one page).
- Every number links back to a commit, PR or release.
- **AI is optional.** Nothing in the core pipeline calls a model. `summarize` and `ask` use local
  Ollama by default; Claude is an opt-in cloud provider.

## Install

```bash
pipx install "gitproof[pdf]"      # or: pip install "gitproof[pdf]"
```

Needs Python 3.11+ and `git`. PDF uses WeasyPrint if installed, otherwise headless Chrome/Edge/Chromium
(set `GITPROOF_BROWSER` to pick one). Without either, export HTML and print it from a browser.

## Quick start

```bash
export GITHUB_TOKEN=ghp_...                 # optional but recommended (rate limits)
gitproof analyze octocat                    # collect + analyze, cached in ~/.gitproof
gitproof show                               # dashboard   (--repo NAME for one project)
gitproof export -f md                       # also json, html, pdf
gitproof export -f pdf --layout summary     # one-page PDF
gitproof bullets                            # resume bullets from measured numbers
gitproof bullets --linkedin                 # short profile summary
gitproof verify octocat-proof-of-work.json  # detect edits to an exported report
```

Useful options: `analyze --since 2023-01-01`, `--alias other@mail.com`, `--exclude-forks`, `--no-blame`,
`config --show`, `cache clear`. Run `gitproof COMMAND --help`.

## Optional AI

```bash
gitproof summarize                 # per-project + overall summary (local Ollama)
gitproof ask "Which projects used Docker?"
gitproof config --ai-provider claude   # cloud: needs ANTHROPIC_API_KEY and one-time consent
```

How it stays honest: code first computes **facts** with ids (`repo:...`, `c:abc1234`, `pr:...`).
The model must answer with claims that cite those ids. A verifier drops any claim with unknown ids,
numbers not present in the data, or no overlap with the cited facts. Questions with no matching
evidence get "No evidence found" without calling the model. With Claude, only the computed fact
digests are sent (never source code, file contents or emails), after you confirm what is sent.

## How the numbers are computed

- Attribution by author email / noreply / name (names only in repos you own).
- Excluded from line counts: lockfiles, vendored/generated/build output, binary assets, data files,
  and commits importing 150+ files or 20,000+ lines (they still count as commits).
- Surviving lines come from `git blame` on the default branch; huge repos are sampled and flagged.
- Commit types, areas and phases are fixed rules, so the same history gives the same result.
- Skills: **strong** = files the developer changed; **inferred** = in a manifest they edited.

The report ends with a methodology section and a SHA-256 data fingerprint. The fingerprint is
tamper-evidence for an exported file, not proof of authorship.

## Privacy

Everything is stored under `~/.gitproof` (`GITPROOF_HOME` to move it). Tokens are never written to
clones or logs; the config file is chmod 600. `gitproof cache clear` removes data.

## Status

Implemented: collection, analysis, dashboard, MD/JSON/HTML/PDF export, optional AI, verification,
resume bullets. Not implemented: interactive TUI, GitLab/Bitbucket, embedding search.
The GitHub client and the Ollama/Claude providers are covered by mocked tests; see CHANGELOG.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests && pytest -q
```

See CONTRIBUTING.md. MIT licensed.
