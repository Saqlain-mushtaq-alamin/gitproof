# GitProof User Guide & CLI Reference

Welcome to the comprehensive user manual for **GitProof**. This guide covers installation, authentication, commands, options, export workflows, PDF engine configurations, and CI/CD automation.

---

## 1. Installation

### System Requirements
- **Python**: 3.11 or newer.
- **Git**: Installed and available in your `PATH`.
- **Operating System**: macOS, Linux, or Windows.

### Recommended Installation (`pipx`)
We recommend using [`pipx`](https://pypa.github.io/pipx/) to run GitProof in an isolated virtual environment:

```bash
# Standard install
pipx install gitproof

# Install with PDF generation support (WeasyPrint)
pipx install "gitproof[pdf]"
```

### Standard `pip` Installation
```bash
pip install "gitproof[pdf]"
```

### Development / Editable Installation
```bash
git clone https://github.com/Saqlain-mushtaq-alamin/gitproof.git
cd gitproof
pip install -e ".[dev]"
```

---

## 2. GitHub Authentication & Tokens

While GitProof can run without a token for public accounts, unauthenticated GitHub API requests are rate-limited to **60 requests/hour**. Providing a Personal Access Token increases your limit to **5,000 requests/hour** and enables identity resolution across large histories.

### Option A: Environment Variable
```bash
# Linux / macOS
export GITHUB_TOKEN="ghp_yourPersonalAccessTokenHere"

# Windows PowerShell
$env:GITHUB_TOKEN="ghp_yourPersonalAccessTokenHere"
```

### Option B: Save via CLI Configuration
```bash
gitproof config --token ghp_yourPersonalAccessTokenHere
```
*Your token is securely saved in `~/.gitproof/config.toml` with restricted `0600` permissions.*

### Including Private Repositories
To analyze private repositories you have access to:
```bash
gitproof analyze your-username --include-private
```
*(Requires a token with `repo` scope).*

---

## 3. CLI Command Reference

### 3.1 `gitproof analyze`
Mines GitHub API metadata and git commit history, executes noise filtering, and caches results.

```bash
gitproof analyze <username> [OPTIONS]
```

| Flag | Type | Description |
|---|---|---|
| `--token` | `TEXT` | GitHub Personal Access Token (or uses `GITHUB_TOKEN`). |
| `--include-private` | `FLAG` | Include private repositories accessible with your token. |
| `--since` | `YYYY-MM-DD` | Only analyze commits on or after this date. |
| `--exclude-forks` | `FLAG` | Ignore forked repositories. |
| `--refresh` | `FLAG` | Force re-mining and re-analysis of all repositories. |
| `--repos` | `TEXT` | Comma-separated list of specific repositories to analyze (e.g. `repo1,repo2`). |
| `--max-repos` | `INT` | Cap analysis to the first $N$ repositories. |
| `--no-blame` | `FLAG` | Skip `git blame` surviving-line calculation (faster analysis). |
| `--alias` | `TEXT` | Extra email address or git author name belonging to you (can repeat). |
| `--no-dashboard` | `FLAG` | Do not automatically display the terminal overview upon completion. |

#### Examples:
```bash
# Analyze full public history
gitproof analyze Saqlain-mushtaq-alamin

# Analyze work done in 2025 and 2026 only
gitproof analyze Saqlain-mushtaq-alamin --since 2025-01-01

# Add personal email aliases for accurate attribution
gitproof analyze Saqlain-mushtaq-alamin --alias my-old-email@gmail.com --alias "John Doe"
```

---

### 3.2 `gitproof show`
Renders an interactive, styled terminal dashboard for the analyzed user.

```bash
gitproof show [username] [OPTIONS]
```

| Flag | Short | Description |
|---|:---:|---|
| `[username]` | | GitHub username (defaults to the last analyzed user). |
| `--repo` | `-r` | Deep-dive into a specific repository. |
| `--all` | | Display all analyzed repositories, not just the top projects. |
| `--no-color` | | Disable Rich ANSI colors. |
| `--width` | | Force a specific terminal output width (e.g. `--width 120`). |

#### Examples:
```bash
# Show overview dashboard
gitproof show

# Inspect details for a single project
gitproof show --repo eco-dms
```

---

### 3.3 `gitproof export`
Exports proof-of-work documentation to **Markdown (`md`)**, **Interactive HTML (`html`)**, **JSON (`json`)**, or **Print-Ready PDF (`pdf`)**.

```bash
gitproof export [username] [OPTIONS]
```

| Flag | Short | Description | Default |
|---|:---:|---|:---:|
| `--format` | `-f` | Output format: `md`, `html`, `json`, or `pdf`. | `md` |
| `--out` | `-o` | Target file path. | `<username>-proof-of-work.<ext>` |
| `--top` | | Limit detailed breakdown to the top $N$ projects. | All |
| `--layout` | | Layout mode: `full` (comprehensive report) or `summary` (one-page). | `full` |
| `--engine` | | PDF rendering engine: `auto`, `weasyprint`, or `browser`. | `auto` |
| `--ai` / `--no-ai` | | Include or exclude cached AI summaries. | `--ai` |
| `--verify` / `--no-verify` | | Include cryptographic SHA-256 fingerprint. | `--verify` |

#### Examples:
```bash
# Export Markdown report
gitproof export -f md

# Export standalone interactive HTML report
gitproof export -f html

# Export 1-page executive summary PDF
gitproof export -f pdf --layout summary -o executive-summary.pdf

# Export structured JSON data for machine verification
gitproof export -f json
```

---

### 3.4 `gitproof summarize` (Optional AI)
Generates evidence-backed repository and profile summaries using local Ollama or Claude.

```bash
gitproof summarize [username] [OPTIONS]
```

| Flag | Short | Description | Default |
|---|:---:|---|:---:|
| `--provider` | `-p` | AI Provider: `ollama` (local) or `claude` (Anthropic). | `ollama` |
| `--model` | `-m` | Model name (e.g. `llama3.2`, `claude-3-5-sonnet-latest`). | Configured |
| `--repo` | `-r` | Summarize only a single repository. | All top repos |
| `--top` | | Number of top repositories to summarize. | `8` |
| `--yes` | `-y` | Skip the cloud AI privacy confirmation prompt. | `False` |
| `--refresh` | | Force recalculation of summaries. | `False` |

---

### 3.5 `gitproof ask` (Optional AI)
Ask questions in natural language about your portfolio or codebase. Answers cite exact commit SHAs and PRs.

```bash
gitproof ask "What experience do I have with FastAPI and async architecture?"
gitproof ask "Which repositories used Docker or Kubernetes?"
```

---

### 3.6 `gitproof bullets`
Generates factual, non-fluffy resume bullet points and LinkedIn summaries derived directly from measured numbers.

```bash
# Generate tailored resume bullet points
gitproof bullets --count 5

# Generate LinkedIn profile summary
gitproof bullets --linkedin
```

---

### 3.7 `gitproof verify`
Validates the cryptographic SHA-256 fingerprint of an exported JSON report to detect tampering.

```bash
gitproof verify Saqlain-mushtaq-alamin-proof-of-work.json
```

---

### 3.8 `gitproof config`
Inspect and update persistent settings in `~/.gitproof/config.toml`.

```bash
# View current configuration
gitproof config --show

# Save GitHub token
gitproof config --token ghp_...

# Save persistent author email aliases
gitproof config --alias mywork@company.com --alias personal@gmail.com

# Switch AI provider
gitproof config --ai-provider ollama --ai-model llama3.2
```

---

### 3.9 `gitproof cache clear`
Manage and delete cached data.

```bash
# Clear all cached databases and clones
gitproof cache clear

# Clear cache for a specific user only
gitproof cache clear octocat

# Clear analysis database but keep git clones
gitproof cache clear --keep-clones
```

---

## 4. PDF Generation Setup

GitProof supports two PDF engines:

### Engine 1: WeasyPrint (Recommended)
WeasyPrint converts the HTML template directly into high-fidelity PDF documents.
```bash
pip install weasyprint
gitproof export -f pdf --engine weasyprint
```

### Engine 2: Headless Browser
If WeasyPrint is not installed, GitProof automatically finds a locally installed browser (Google Chrome, Microsoft Edge, Chromium, or Brave) and renders the PDF via headless Chrome devtools protocol:
```bash
# Specify custom browser executable if needed:
export GITPROOF_BROWSER="/usr/bin/google-chrome"
gitproof export -f pdf --engine browser
```

---

## 5. CI/CD Automation (GitHub Actions)

You can automatically generate and host your Proof of Work report using GitHub Actions.

Create `.github/workflows/gitproof.yml`:

```yaml
name: Generate Proof of Work

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 0 * * 0' # Every Sunday at midnight
  workflow_dispatch:

jobs:
  build-proof:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install GitProof
        run: pip install gitproof

      - name: Generate Reports
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gitproof analyze ${{ github.repository_owner }}
          gitproof export -f md -o proof-of-work.md
          gitproof export -f html -o proof-of-work.html
          gitproof export -f json -o proof-of-work.json

      - name: Commit and Push Updated Reports
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add proof-of-work.*
          git commit -m "docs: update proof of work [skip ci]" || exit 0
          git push
```

---

## 6. Troubleshooting & FAQ

### Q: Why are some of my commits missing from the count?
1. **Email Mismatch**: You may have committed using an email not linked to your GitHub account. Fix:
   ```bash
   gitproof config --alias your-other-email@example.com
   gitproof analyze your-username --refresh
   ```
2. **Bulk Imports**: Commits that add $>150$ files or $>20,000$ lines at once are counted as commits, but their line additions are zeroed out to prevent skewing.
3. **Forks**: By default, forks are analyzed. Use `--exclude-forks` if you only want original repositories.

### Q: Rate limit error encountered?
Unauthenticated API limits expire every hour. Set `GITHUB_TOKEN` to unlock 5,000 requests/hour.
