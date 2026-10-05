"""Noise filtering: decide which changed files and commits should NOT count as authored work."""
from __future__ import annotations

import re

LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "bun.lock", "cargo.lock", "poetry.lock", "pipfile.lock", "uv.lock", "pdm.lock",
    "composer.lock", "gemfile.lock", "pubspec.lock", "go.sum", "gradle.lockfile",
    "packages.lock.json", "flake.lock", "podfile.lock", "mix.lock", "conan.lock",
}
VENDOR_DIRS = {
    "node_modules", "vendor", "third_party", "third-party", "thirdparty", "bower_components",
    "pods", ".venv", "venv", "site-packages", ".yarn", ".pnpm-store", "__pypackages__",
}
BUILD_DIRS = {
    "dist", "build", "target", ".next", ".nuxt", ".dart_tool", "__pycache__", ".gradle",
    ".idea", ".vscode", "coverage", "htmlcov", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".svelte-kit", ".turbo", ".cache", "deriveddata",
}
GENERATED_RE = re.compile("|".join([
    r"\.(g|freezed|gr|mocks)\.dart$", r"_pb2(_grpc)?\.pyi?$", r"\.pb\.go$",
    r"generated_plugin_registrant", r"generatedpluginregistrant", r"(^|/)generated/",
    r"\.generated\.", r"project\.pbxproj$", r"gradle-wrapper\.(jar|properties)$",
    r"(^|/)(gradlew|gradlew\.bat|mvnw|mvnw\.cmd)$", r"\.designer\.cs$",
    r"(^|/)\.flutter-plugins(-dependencies)?$", r"(^|/)\.packages$", r"(^|/)\.ds_store$",
]))
ASSET_EXTS = {
    "png", "jpg", "jpeg", "gif", "webp", "ico", "icns", "bmp", "tif", "tiff", "svg", "psd",
    "mp3", "wav", "ogg", "flac", "mp4", "mov", "webm", "avi", "mkv", "ttf", "otf", "woff",
    "woff2", "eot", "pdf", "zip", "tar", "gz", "tgz", "7z", "rar", "jar", "aar", "apk", "exe",
    "dll", "so", "dylib", "a", "o", "class", "pyc", "bin", "dat", "db", "sqlite", "sqlite3",
    "onnx", "pt", "pth", "ckpt", "safetensors", "h5", "hdf5", "npy", "npz", "pkl", "pickle",
    "gguf", "tflite", "mlmodel", "parquet", "csv", "tsv", "jsonl", "ndjson",
}

# A single commit adding this much is treated as an import/vendoring, not authored work.
BULK_MIN_FILES = 150
BULK_ADD_RATIO = 0.9
BULK_HUGE_ADDS = 20_000

EXT_LANG = {
    "py": "Python", "pyi": "Python", "rs": "Rust", "js": "JavaScript", "mjs": "JavaScript",
    "cjs": "JavaScript", "jsx": "JavaScript", "ts": "TypeScript", "tsx": "TypeScript",
    "dart": "Dart", "kt": "Kotlin", "kts": "Kotlin", "java": "Java", "swift": "Swift",
    "m": "Objective-C", "mm": "Objective-C", "c": "C", "h": "C", "cpp": "C++", "cc": "C++",
    "cxx": "C++", "hpp": "C++", "cs": "C#", "go": "Go", "rb": "Ruby", "php": "PHP",
    "sh": "Shell", "bash": "Shell", "zsh": "Shell", "ps1": "PowerShell", "html": "HTML",
    "htm": "HTML", "css": "CSS", "scss": "SCSS", "sass": "SCSS", "less": "CSS", "vue": "Vue",
    "svelte": "Svelte", "sql": "SQL", "lua": "Lua", "r": "R", "scala": "Scala", "jl": "Julia",
    "sol": "Solidity", "ex": "Elixir", "exs": "Elixir", "hs": "Haskell", "zig": "Zig",
    "cu": "CUDA", "ipynb": "Jupyter Notebook", "tf": "Terraform", "proto": "Protocol Buffers",
    "glsl": "GLSL", "wgsl": "WGSL", "v": "Verilog", "vhd": "VHDL",
}


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1] if "." in name else ""


def noise_reason(path: str) -> str | None:
    """Why a path should be ignored when measuring authored work (None = counts)."""
    low = path.replace("\\", "/").lower()
    parts = low.split("/")
    name, dirs = parts[-1], parts[:-1]
    if name in LOCKFILES:
        return "lockfile"
    if any(d in VENDOR_DIRS for d in dirs):
        return "vendored"
    if any(d in BUILD_DIRS for d in dirs):
        return "build output"
    if name.endswith((".min.js", ".min.css", ".map")) or ".bundle." in name:
        return "minified"
    if GENERATED_RE.search(low):
        return "generated"
    if _ext(name) in ASSET_EXTS:
        return "asset/data"
    return None


def language_for(path: str) -> str | None:
    return EXT_LANG.get(_ext(path.replace("\\", "/").rsplit("/", 1)[-1].lower()))


def is_bulk_commit(n_files: int, additions: int, deletions: int) -> bool:
    """True for imports/vendoring commits that would otherwise inflate line counts."""
    total = additions + deletions
    if total == 0:
        return False
    ratio = additions / total
    if n_files >= BULK_MIN_FILES and ratio >= BULK_ADD_RATIO:
        return True
    return additions >= BULK_HUGE_ADDS and ratio >= 0.98
