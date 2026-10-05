# Contributing

    pip install -e ".[dev]"
    ruff check src tests
    pytest -q

Principles: the core pipeline is deterministic and works offline once data is
cached; AI is optional and every AI claim must cite fact ids and pass the
verifier (`gitproof/ai/verify.py`). Tests use a real git fixture repo plus a mocked
GitHub API, so no network or token is needed. Please add a test with every fix.
