# GitProof

<div align="center">

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Local First](https://img.shields.io/badge/privacy-local--first-green.svg)](#privacy--security)
[![Zero Hallucinations](https://img.shields.io/badge/AI-evidence--grounded-purple.svg)](#optional-zero-hallucination-ai)

**Turn a GitHub username into an evidence-backed developer profile and proof-of-work report.**  
*Free, local-first, deterministic, and runs directly in your terminal.*

[Quick Start](#-quick-start) • [Sample Outputs](#-real-world-sample-outputs) • [Documentation Hub](docs/README.md) • [Architecture](docs/architecture.md) • [How It Works](docs/how-it-works.md) • [User Guide](docs/user-guide.md)

</div>

---

## 💡 Why GitProof?

Resumes and self-reported skill lists are full of buzzwords, inflated claims, and unverified summaries. GitHub profile pages only show commit green squares, which count whitespace edits, empty commits, or vendored code equally.

**GitProof solves this by mining the actual git commit history and repository trees:**
- 🔍 **Mines Real Git Repositories**: Clones and inspects repositories locally to analyze commits, branches, file diffs, pull requests, issues, and releases.
- 🧹 **Aggressive Noise Filtering**: Automatically detects and excludes package lockfiles (`package-lock.json`, `poetry.lock`, `cargo.lock`), vendored code (`node_modules/`, `vendor/`), build artifacts, minified files, generated code, and bulk imports.
- 📐 **Surviving Lines via `git blame`**: Measures the lines of code written by the developer that **actually survive in production** at HEAD.
- 🏷️ **Skill Confidence with Direct Evidence**: Categorizes skills as **strong** (files the user authored) or **inferred** (manifest dependencies the user touched), with clickable commit links for proof.
- 🛡️ **Cryptographic Tamper-Evidence**: Generates SHA-256 digital signatures for reports so any manual edits or tampering can be instantly detected with `gitproof verify`.
- 🤖 **Optional, Zero-Hallucination AI**: Uses local Ollama by default (or opt-in Claude). All AI claims are verified against strict pre-computed fact IDs—if a claim invents numbers or cites fake facts, it is dropped before you see it.

---

## 📊 Real-World Sample Outputs

Inspect complete, production-ready proof-of-work reports generated from real GitHub activity:

| Format | Sample File | Highlights |
|---|---|---|
| **📄 Markdown Report** | [**`Saqlain-mushtaq-alamin-proof-of-work.md`**](Saqlain-mushtaq-alamin-proof-of-work.md) | Complete 12-section evidence report with clickable commit URLs, skill matrix, timeline, and methodology. |
| **🌐 Interactive HTML** | [**`Saqlain-mushtaq-alamin-proof-of-work.html`**](Saqlain-mushtaq-alamin-proof-of-work.html) | Standalone single-file interactive report with dark/light mode, live search filters, and collapsible repo details. |

> [!TIP]
> See [**`docs/samples.md`**](docs/samples.md) for a detailed walkthrough on how to review and verify these sample reports.

---

## 🚀 Quick Start

### 1. Install
```bash
# Recommended: install with pipx
pipx install "gitproof[pdf]"

# Or with pip
pip install "gitproof[pdf]"
```

*Requirements: Python 3.11+ and `git` installed on your system.*

### 2. Set Up Token (Recommended)
```bash
export GITHUB_TOKEN=ghp_yourPersonalAccessTokenHere
# Or store it permanently:
gitproof config --token ghp_yourPersonalAccessTokenHere
```

### 3. Analyze and Export
```bash
# 1. Analyze any GitHub account (cached locally in ~/.gitproof)
gitproof analyze octocat

# 2. View rich interactive terminal dashboard
gitproof show

# 3. Export proof-of-work report (Markdown, HTML, JSON, or PDF)
gitproof export -f md
gitproof export -f html
gitproof export -f pdf --layout summary  # One-page executive PDF
gitproof export -f json

# 4. Generate factual resume bullet points & LinkedIn summary (no AI required)
gitproof bullets
gitproof bullets --linkedin

# 5. Verify the integrity of an exported report
gitproof verify octocat-proof-of-work.json
```

---

## 🖥️ Terminal Dashboard

When you run `gitproof show`, GitProof renders a comprehensive dashboard directly in your console:

```text
MD AL AMIN (Saqlain-mushtaq-alamin)
26 repositories with authored work · 2,632 commits · 1.7 years active
Focus: Web · Mobile · Systems

Top Languages:
Python       ████████████████████ 45.2% (1,078 commits, 98,412 surviving lines)
TypeScript   ███████████████       33.8% (804 commits, 71,209 surviving lines)
CSS          ████                  7.1%  (126 commits, 14,881 surviving lines)

Top Projects:
• eco-dms      [Quality 55/100]  438 commits (69,249 lines)  TypeScript, React, Expo
• Poise-       [Quality 80/100]  673 commits (40,541 lines)  Python, Tauri, FastAPI
• ARIA         [Quality 65/100]  126 commits (24,370 lines)  Python
• VeritasCore  [Quality 90/100]  135 commits (14,621 lines)  Python, Transformers
```

---

## 🧠 Optional Zero-Hallucination AI

GitProof does **not** rely on AI for its core metrics—everything is calculated deterministically. However, GitProof provides optional AI summarization and Q&A powered by a **strict evidence verification layer**:

```bash
# Generate evidence-backed project & profile summaries (uses local Ollama by default)
gitproof summarize

# Ask natural language questions with commit/PR citations
gitproof ask "Which projects demonstrate experience with async backends?"
```

### How GitProof Keeps AI Honest:
1. **Pre-computed Fact Digest**: The engine extracts atomic, verifiable facts from the database (e.g. `repo:...`, `c:<sha>`, `pr:...`, `skill:...`).
2. **Citation Requirement**: The model must provide structured claims citing specific fact IDs.
3. **Triple-Gate Verification**:
   - ❌ Drops claims citing non-existent fact IDs.
   - ❌ Drops claims stating numbers not found in the source facts.
   - ❌ Drops claims lacking lexical overlap with the cited evidence.
4. **Privacy First**: With local Ollama, no data leaves your machine. With Claude, only compact metadata digests are sent after explicit consent—source code and emails are never sent.

---

## 📚 Complete Documentation Hub

For detailed guides, deep dives, and manuals, visit the **[Documentation Hub](docs/README.md)**:

- 📖 [**User Guide & CLI Reference**](docs/user-guide.md): Complete guide to all commands, flags, PDF engines, and CI/CD GitHub Actions automation.
- ⚙️ [**System Architecture**](docs/architecture.md): Module diagrams, SQLite schema, caching strategies, and data pipeline lifecycle.
- 🔬 [**How It Works (Mechanics & Algorithms)**](docs/how-it-works.md): Detailed explanation of noise filters, `git blame` calculations, quality scoring rubric (0–100), and skill detection.
- 📊 [**Output Samples & Verification**](docs/samples.md): In-depth guide to reviewing and verifying GitProof reports.

---

## 🔒 Privacy & Security

- **100% Local Storage**: Analysis databases and bare git clones reside in `~/.gitproof/` (or `$GITPROOF_HOME`).
- **Secure Configuration**: `~/.gitproof/config.toml` is written with `0600` user-only permissions.
- **Clean Git Clones**: Access tokens are never stored in git remote URLs or commit logs.
- **Cache Management**: Delete all cached data anytime with `gitproof cache clear`.

---

## 🛠️ Development & Testing

```bash
# Clone the repository
git clone https://github.com/Saqlain-mushtaq-alamin/gitproof.git
cd gitproof

# Install development dependencies
pip install -e ".[dev]"

# Run code linter and test suite
ruff check src tests
pytest -q
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
