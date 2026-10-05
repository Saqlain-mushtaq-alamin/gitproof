"""GitHub REST client with ETag caching, pagination, retries and rate-limit handling."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from ..db import Store

API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status
        self.message = message


class NotFound(GitHubError):
    pass


class RateLimited(GitHubError):
    def __init__(self, reset_at: int | None, authenticated: bool):
        hint = "" if authenticated else " Set GITHUB_TOKEN (or pass --token) for 5,000 requests/hour."
        when = ""
        if reset_at:
            when = f" Limit resets in about {max(0, reset_at - int(time.time())) // 60 + 1} min."
        super().__init__(403, f"rate limit exceeded.{when}{hint}")
        self.reset_at = reset_at


class GitHubClient:
    def __init__(self, store: Store, token: str | None = None,
                 transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, base_url: str = API):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "gitproof/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.store = store
        self.authenticated = bool(token)
        self._sleep = sleep
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=30.0,
                                  transport=transport, follow_redirects=True)
        self.remaining: dict[str, int] = {}
        self.reset: dict[str, int] = {}
        self.requests_made = 0
        self.cache_hits = 0

    def close(self) -> None:
        self._http.close()

    def _track(self, resp: httpx.Response) -> None:
        resource = resp.headers.get("x-ratelimit-resource", "core")
        if "x-ratelimit-remaining" in resp.headers:
            try:
                self.remaining[resource] = int(resp.headers["x-ratelimit-remaining"])
                self.reset[resource] = int(resp.headers.get("x-ratelimit-reset", "0"))
            except ValueError:
                pass

    def refresh_limits(self) -> None:
        """Populate remaining quota; /rate_limit does not count against the limit."""
        try:
            resp = self._http.get("/rate_limit")
            if resp.status_code == 200:
                for name, info in resp.json().get("resources", {}).items():
                    self.remaining[name] = int(info.get("remaining", 0))
                    self.reset[name] = int(info.get("reset", 0))
        except (httpx.HTTPError, ValueError):
            pass

    def budget_ok(self, resource: str = "core", reserve: int = 8) -> bool:
        left = self.remaining.get(resource)
        return left is None or left > reserve

    def _request(self, path: str, params: dict[str, Any] | None = None) -> str:
        request = self._http.build_request("GET", path, params=params)
        key = str(request.url)
        cached = self.store.get_http(key)
        headers: dict[str, str] = {}
        if cached and cached[0]:
            headers["If-None-Match"] = cached[0]
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                resp = self._http.get(path, params=params, headers=headers)
            except httpx.TransportError as exc:
                last_error = exc
                self._sleep(2 ** attempt)
                continue
            self.requests_made += 1
            self._track(resp)
            code = resp.status_code
            if code == 304 and cached:
                self.cache_hits += 1
                return cached[1]
            if code in (500, 502, 503, 504):
                self._sleep(2 ** attempt)
                continue
            if code in (403, 429) and self._handle_limit(resp):
                continue
            if code == 404:
                raise NotFound(404, f"{path} not found")
            if code >= 400:
                raise GitHubError(code, _message(resp))
            etag = resp.headers.get("etag")
            if etag:
                self.store.put_http(key, etag, resp.text)
            return resp.text
        raise GitHubError(0, f"network error contacting GitHub: {last_error}")

    def _handle_limit(self, resp: httpx.Response) -> bool:
        """True = retry. Raises RateLimited / GitHubError when retrying is pointless."""
        retry_after = resp.headers.get("retry-after")
        if retry_after and retry_after.isdigit() and int(retry_after) <= 60:
            self._sleep(int(retry_after))
            return True
        resource = resp.headers.get("x-ratelimit-resource", "core")
        if resp.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in _message(resp).lower():
            raise RateLimited(self.reset.get(resource) or None, self.authenticated)
        raise GitHubError(resp.status_code, _message(resp))

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return json.loads(self._request(path, params))

    def paginate(self, path: str, params: dict[str, Any] | None = None, key: str | None = None,
                 limit: int | None = None, max_pages: int = 10) -> list[Any]:
        out: list[Any] = []
        for page in range(1, max_pages + 1):
            data = self.get_json(path, dict(params or {}, per_page=100, page=page))
            items = data[key] if key else data
            out.extend(items)
            if len(items) < 100 or (limit and len(out) >= limit):
                break
        return out[:limit] if limit else out

    def user(self, login: str) -> dict[str, Any]:
        return self.get_json(f"/users/{login}")

    def authenticated_login(self) -> str | None:
        if not self.authenticated:
            return None
        try:
            return self.get_json("/user").get("login")
        except GitHubError:
            return None

    def repos(self, login: str, include_private: bool = False) -> list[dict[str, Any]]:
        if include_private and self.authenticated_login() == login:
            return self.paginate("/user/repos",
                                 {"affiliation": "owner", "visibility": "all", "sort": "pushed"})
        return self.paginate(f"/users/{login}/repos", {"type": "owner", "sort": "pushed"})

    def author_commits(self, full_name: str, login: str) -> list[dict[str, Any]]:
        """Commits GitHub attributes to `login`; used to learn the user's git identities."""
        try:
            return self.get_json(f"/repos/{full_name}/commits", {"author": login, "per_page": 30})
        except GitHubError as exc:
            if exc.status in (404, 409):
                return []
            raise

    def releases(self, full_name: str) -> list[dict[str, Any]]:
        try:
            return self.paginate(f"/repos/{full_name}/releases", max_pages=3)
        except NotFound:
            return []

    def search_items(self, login: str, kind: str) -> list[dict[str, Any]]:
        return self.paginate("/search/issues",
                             {"q": f"author:{login} type:{kind}", "sort": "created", "order": "desc"},
                             key="items", limit=1000)

    def search_count(self, query: str) -> int:
        return int(self.get_json("/search/issues", {"q": query, "per_page": 1}).get("total_count", 0))


def _message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("message", resp.text[:200]))
    except ValueError:
        return resp.text[:200]
