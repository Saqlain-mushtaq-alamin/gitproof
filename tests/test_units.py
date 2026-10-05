from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from gitproof.analyze import classify, filters, phases, quality, skills
from gitproof.analyze.attribution import Identity, build_identity
from gitproof.collect import git_miner
from gitproof.collect.github_api import GitHubClient, GitHubError, NotFound, RateLimited
from gitproof.config import Config
from gitproof.db import Store
from gitproof.util import clip, mask_email, parse_dt


# ---- filters ------------------------------------------------------------------------------
@pytest.mark.parametrize("path,expected", [
    ("package-lock.json", "lockfile"), ("app/Cargo.lock", "lockfile"),
    ("node_modules/x/index.js", "vendored"), ("src/vendor/lib.py", "vendored"),
    ("build/out.js", "build output"), ("static/app.min.js", "minified"),
    ("lib/model.g.dart", "generated"), ("api/foo_pb2.py", "generated"),
    ("assets/logo.png", "asset/data"), ("data/train.csv", "asset/data"),
    ("src/main.py", None), ("README.md", None), ("src/ui/Button.tsx", None),
])
def test_noise_reason(path, expected):
    assert filters.noise_reason(path) == expected


def test_language_for_and_bulk():
    assert filters.language_for("a/b/main.rs") == "Rust"
    assert filters.language_for("README.md") is None
    assert filters.is_bulk_commit(200, 5000, 10)
    assert not filters.is_bulk_commit(200, 100, 5000)       # mostly deletions
    assert not filters.is_bulk_commit(10, 500, 0)           # small
    assert filters.is_bulk_commit(5, 25_000, 0)
    assert not filters.is_bulk_commit(0, 0, 0)


# ---- attribution --------------------------------------------------------------------------
def test_identity_matching():
    ident = build_identity("alice", {"name": "Alice Dev", "email": None}, ["old@x.org"],
                           {"alice@example.com"}, {"alice d"})
    assert ident.matches("alice@example.com", "whoever")
    assert ident.matches("OLD@x.org", "")
    assert ident.matches("12345+Alice@users.noreply.github.com", "x")
    assert ident.matches("alice@users.noreply.github.com", "x")
    assert not ident.matches("bob@users.noreply.github.com", "Bob")
    assert not ident.matches("stranger@example.com", "Alice Dev")          # name only if allowed
    assert ident.matches("stranger@example.com", "Alice Dev", allow_name=True)
    assert not ident.matches("stranger@example.com", "github", allow_name=True)


def test_identity_ignores_generic_names_and_fingerprint_changes():
    i = Identity("a")
    i.add("root")
    i.add("noreply@github.com")
    assert not i.names and not i.emails
    before = i.fingerprint()
    i.add("a@b.c")
    assert i.fingerprint() != before


# ---- classification ---------------------------------------------------------------------
@pytest.mark.parametrize("subject,files,expected", [
    ("feat(api): add endpoint", [], "feature"),
    ("fix: null pointer", [], "fix"),
    ("Initial commit", [], "init"),
    ("Merge branch 'x'", [], "merge"),
    ("Fix crash when peer disconnects", [("a.py", 3, 1)], "fix"),
    ("update stuff", [("tests/test_a.py", 5, 0)], "test"),
    ("tweak", [("README.md", 2, 1)], "docs"),
    ("tweak", [(".github/workflows/ci.yml", 2, 1)], "ci"),
    ("Refactor transfer module", [("a.py", 5, 5)], "refactor"),
    ("stuff", [("a.py", 50, 1)], "feature"),
    ("stuff", [("a.py", 1, 50)], "refactor"),
])
def test_classify_commit(subject, files, expected):
    assert classify.classify_commit(subject, False, files) == expected


@pytest.mark.parametrize("path,area", [
    ("tests/test_x.py", "Testing"), ("src/net/socket.rs", "Networking"),
    (".github/workflows/ci.yml", "CI/DevOps"), ("Dockerfile", "CI/DevOps"),
    ("pyproject.toml", "Build & Config"), ("docs/guide.md", "Documentation"),
    ("src/models/train.py", "ML/Data"), ("app/ui/screen.dart", "UI"),
    ("src/lib.rs", "Core Logic"), ("android/app/src/main/AndroidManifest.xml", "Platform Integration"),
    ("src/auth/jwt.ts", "Security"), ("src/db/migrations/001.sql", "Database"),
])
def test_area_for_path(path, area):
    assert classify.area_for_path(path) == area


def test_custom_area_tokens():
    assert classify.area_for_path("src/foo/nearby.py") == "Core Logic"
    assert classify.area_for_path("src/foo/nearby.py", {"Networking": ["nearby"]}) == "Networking"


# ---- phases ---------------------------------------------------------------------------------
def mk(day: int, typ="feature", area="Core Logic", lines=10, sha=None):
    base = datetime(2025, 1, 1, tzinfo=UTC)
    return {"date": base + timedelta(days=day), "type": typ, "area": area, "lines": lines,
            "sha": sha or f"s{day}", "subject": "x"}


def test_phases_split_on_gaps_and_cover_all_commits():
    commits = [mk(i, "init" if i == 0 else "feature") for i in range(6)]
    commits += [mk(200 + i, "fix") for i in range(5)]
    out = phases.build_phases(commits)
    assert len(out) == 2
    assert sum(p["commits"] for p in out) == 11
    assert out[0]["label"].startswith("Project setup")
    assert out[1]["start"] > out[0]["end"]


def test_phases_continuous_history_split_evenly_and_tiny_stays_single():
    out = phases.build_phases([mk(i * 2) for i in range(30)])
    assert len(out) == 3 and sum(p["commits"] for p in out) == 30
    assert len(phases.build_phases([mk(0), mk(1)])) == 1
    assert phases.build_phases([]) == []


def test_phases_cap_at_max():
    commits = []
    for block in range(10):
        commits += [mk(block * 400 + i) for i in range(4)]
    assert len(phases.build_phases(commits)) <= phases.MAX_PHASES


# ---- skills ---------------------------------------------------------------------------------
def test_manifest_parsers():
    assert {"react", "jest"} <= skills.parse_package_json(
        '{"dependencies":{"react":"1"},"devDependencies":{"jest":"1"}}')
    assert skills.parse_package_json("not json") == set()
    assert {"fastapi", "torch"} <= skills.parse_requirements("fastapi>=0.1\n# c\ntorch==2 ; python_version>'3'\n-r other.txt\n")
    assert {"typer", "pytest"} <= skills.parse_pyproject(
        '[project]\ndependencies=["Typer>=1"]\n[project.optional-dependencies]\ndev=["pytest"]\n')
    assert "tokio" in skills.parse_cargo('[dependencies]\ntokio = "1"\n')
    assert {"flutter", "dio"} <= skills.parse_pubspec(
        "name: x\ndependencies:\n  flutter:\n    sdk: flutter\n  dio: ^5\ndev_dependencies:\n  flutter_test:\n")
    assert "github.com/gin-gonic/gin" in skills.parse_go_mod("require github.com/gin-gonic/gin v1.9.0\n")


def test_detect_frameworks_and_repo_skills():
    fw = skills.detect_frameworks({"pyproject.toml": '[project]\ndependencies=["fastapi","torch"]\n'})
    assert fw["FastAPI"]["category"] == "Framework" and "PyTorch" in fw
    d = datetime(2025, 1, 1, tzinfo=UTC)
    touches = [("a" * 40, d, "pyproject.toml", 3), ("a" * 40, d, "src/x.py", 10),
               ("b" * 40, d + timedelta(days=2), "Dockerfile", 2),
               ("c" * 40, d, "node_modules/x.js", 99)]
    out = {s["name"]: s for s in skills.repo_skills(touches, fw)}
    assert out["Python"]["confidence"] == "strong" and out["Python"]["lines"] == 10
    assert out["FastAPI"]["confidence"] == "inferred"
    assert out["Docker"]["commits"] == 1
    assert "JavaScript" not in out  # vendored file ignored
    merged = skills.merge_skills({"r1": list(out.values()), "r2": list(out.values())})
    py = next(m for m in merged if m["name"] == "Python")
    assert py["commits"] == 2 and py["repos"] == ["r1", "r2"]


# ---- quality --------------------------------------------------------------------------------
def test_extract_purpose():
    readme = "# T\n\n[![b](x)](y)\n\nThis tool does a very useful thing for developers daily.\nMore.\n\n## Install\n"
    assert quality.extract_purpose(readme, "desc").startswith("This tool does a very useful")
    assert quality.extract_purpose("# T\n\nshort\n", "From description") == "From description"
    assert quality.extract_purpose(None, None) == "No description available."


def test_assess_score_bounds():
    empty = quality.assess([], None, 0)
    assert empty["score"] == 0
    full = quality.assess(
        [("src/a.py", 10), ("tests/test_a.py", 10), (".github/workflows/ci.yml", 1),
         ("LICENSE", 1), ("Dockerfile", 1), ("docs/a.md", 1), (".pre-commit-config.yaml", 1)],
        "# A\n## Install\n```x```\n![i](i)\n" + "text " * 100 + "\n## Usage\n### More\n", 4)
    assert 80 <= full["score"] <= 100


# ---- git log parsing ---------------------------------------------------------------------------
def test_parse_log_lines_handles_binary_and_multiple_commits():
    RS, US = "\x1e", "\x1f"
    lines = [
        f"{RS}{'a'*40}{US}Al{US}al@x.com{US}2025-01-01T10:00:00+00:00{US}{'p'*40}{US}first\n",
        "\n", "10\t2\tsrc/a.py\n", "-\t-\timg.png\n",
        f"{RS}{'b'*40}{US}Bo{US}bo@x.com{US}2025-01-02T10:00:00+06:00{US}{'p'*40} {'q'*40}{US}Merge x\n",
    ]
    out = list(git_miner.parse_log_lines(lines))
    assert len(out) == 2
    assert out[0].files == [(10, 2, "src/a.py"), (0, 0, "img.png")]
    assert out[1].parents == 2
    assert out[1].authored_at == parse_dt("2025-01-02T04:00:00Z")


def test_util_helpers():
    assert mask_email("alice@example.com") == "a***@example.com"
    assert clip("x" * 50, 10) == "xxxxxxx..."
    assert clip("short", 10) == "short"


# ---- GitHub client -------------------------------------------------------------------------------
def client_with(handler, tmp_path, token=None):
    store = Store("t", tmp_path / "t.db")
    return GitHubClient(store, token, transport=httpx.MockTransport(handler), sleep=lambda s: None), store


def test_client_etag_cache_and_304(tmp_path):
    calls = []

    def handler(req):
        calls.append(req.headers.get("if-none-match"))
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json={"login": "a"}, headers={"etag": '"v1"'})

    c, _ = client_with(handler, tmp_path)
    assert c.user("a") == {"login": "a"}
    assert c.user("a") == {"login": "a"}
    assert calls == [None, '"v1"'] and c.cache_hits == 1


def test_client_not_found_and_errors(tmp_path):
    c, _ = client_with(lambda r: httpx.Response(404, json={"message": "Not Found"}), tmp_path)
    with pytest.raises(NotFound):
        c.user("zzz")
    c, _ = client_with(lambda r: httpx.Response(422, json={"message": "bad"}), tmp_path)
    with pytest.raises(GitHubError) as e:
        c.user("zzz")
    assert e.value.status == 422


def test_client_rate_limit_message_mentions_token(tmp_path):
    def handler(req):
        return httpx.Response(403, json={"message": "API rate limit exceeded"},
                              headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"})

    c, _ = client_with(handler, tmp_path)
    with pytest.raises(RateLimited) as e:
        c.user("a")
    assert "GITHUB_TOKEN" in str(e.value)
    c2, _ = client_with(handler, tmp_path, token="tok")
    with pytest.raises(RateLimited) as e2:
        c2.user("a")
    assert "GITHUB_TOKEN" not in str(e2.value)


def test_client_retries_server_errors_then_succeeds(tmp_path):
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        return httpx.Response(502) if state["n"] < 3 else httpx.Response(200, json={"ok": 1})

    c, _ = client_with(handler, tmp_path)
    assert c.get_json("/x") == {"ok": 1} and state["n"] == 3


def test_client_gives_up_on_network_errors(tmp_path):
    def handler(req):
        raise httpx.ConnectError("down")

    c, _ = client_with(handler, tmp_path)
    with pytest.raises(GitHubError, match="network error"):
        c.get_json("/x")


def test_client_pagination(tmp_path):
    def handler(req):
        page = int(req.url.params["page"])
        n = 100 if page < 3 else 7
        return httpx.Response(200, json=[{"i": page}] * n)

    c, _ = client_with(handler, tmp_path)
    assert len(c.paginate("/things")) == 207


# ---- config ----------------------------------------------------------------------------------------
def test_config_roundtrip(gp_home):
    cfg = Config(token="abc", aliases=["a@b.c"], last_user="alice",
                 area_tokens={"Networking": ["nearby"]})
    cfg.save()
    loaded = Config.load()
    assert loaded.token == "abc" and loaded.aliases == ["a@b.c"]
    assert loaded.last_user == "alice" and loaded.area_tokens == {"Networking": ["nearby"]}
    assert Config.load().max_repo_size_mb == 300


def test_plural_helper():
    from gitproof.util import plural
    assert plural(1, "repository", "repositories") == "1 repository"
    assert plural(0, "repository", "repositories") == "0 repositories"
    assert plural(1234, "commit") == "1,234 commits"


def test_blame_counts_carry_commit_sha(tmp_path):
    from conftest import commit, git
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "one", "A", "a@x.com", "2025-01-01T00:00:00+00:00", {"f.py": "a\nb\n"})
    sha1 = git(repo, "rev-parse", "HEAD").strip()
    commit(repo, "two", "B", "b@x.com", "2025-01-02T00:00:00+00:00", {"f.py": "a\nb\nc\n"})
    sha2 = git(repo, "rev-parse", "HEAD").strip()
    counts = git_miner.blame_counts(repo / ".git", "f.py")
    assert counts[("a@x.com", "A", sha1)] == 2
    assert counts[("b@x.com", "B", sha2)] == 1
