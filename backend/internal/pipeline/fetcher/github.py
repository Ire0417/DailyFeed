"""
GitHub fetcher - 拉取用户动态，基于 `internal.infrastructure.external.github_client.GitHubClient`。

暴露统一的 `async fetch(username_or_url, limit)` 接口，同时兼容把 GitHub URL 当参数传入。
"""
import re

from internal.infrastructure.monitoring.logger import get_logger
from internal.infrastructure.external.github_client import GitHubClient

logger = get_logger("github_fetcher")

_client = GitHubClient()


async def fetch(source: str, limit: int = 20) -> list[dict]:
    """
    source 可以是:
      - GitHub 用户名, 如 "torvalds"
      - GitHub atom URL, 如 "https://github.com/torvalds.atom"
      - releases URL, 如 "https://github.com/tiangolo/fastapi/releases.atom"
      - trending:daily / trending:weekly / trending:monthly
          可选附加语言: trending:daily/python  / trending:daily?language=python
      - topstarred:10000  (min_stars)
          可选附加语言: topstarred:10000/python
    """
    s = (source or "").strip()
    if not s:
        return []

    # ---- 1) trending:<period>[/language] ----
    if s.lower().startswith("trending:"):
        return await _fetch_trending(s, limit=limit)

    # ---- 2) topstarred:<min_stars>[/language] ----
    if s.lower().startswith("topstarred:"):
        return await _fetch_top_starred(s, limit=limit)

    # ---- 3) releases? ----
    if "/releases.atom" in s:
        m = re.search(r"github\.com/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-.]+)/releases", s)
        if m:
            events = await _client.list_releases(m.group(1), m.group(2), limit=limit)
            return _events_to_dicts(events)
    # ---- 4) plain user ----
    username = s
    if "github.com/" in s:
        m = re.search(r"github\.com/([A-Za-z0-9_\-]+)\.atom", s)
        if m:
            username = m.group(1)
        else:
            m = re.search(r"github\.com/([A-Za-z0-9_\-]+)", s)
            if m:
                username = m.group(1)
    events = await _client.list_events(username, limit=limit)
    return _events_to_dicts(events)


async def _fetch_trending(source: str, limit: int = 20) -> list[dict]:
    """Parse "trending:daily/python" -> call GitHubClient.fetch_trending()."""
    rest = source[len("trending:"):].strip()
    if not rest:
        rest = "daily"
    # allow "daily/python" or "daily?language=python"
    language: str | None = None
    since = "daily"
    if "/" in rest:
        parts = rest.split("/", 1)
        since = parts[0].strip().lower()
        language = parts[1].strip().lower() or None
    elif "?" in rest:
        parts = rest.split("?", 1)
        since = parts[0].strip().lower()
        # try to parse ?language=xxx
        import urllib.parse as _up
        try:
            qs = _up.parse_qs(parts[1])
            if "language" in qs:
                language = qs["language"][0].strip().lower()
        except Exception:
            language = None
    else:
        since = rest.lower()
    events = await _client.fetch_trending(since=since, language=language, limit=limit)
    return _events_to_dicts(events)


async def _fetch_top_starred(source: str, limit: int = 20) -> list[dict]:
    """Parse "topstarred:10000/python" -> call GitHubClient.fetch_top_starred()."""
    rest = source[len("topstarred:"):].strip()
    if not rest:
        rest = "10000"
    min_stars = 10000
    language: str | None = None
    if "/" in rest:
        parts = rest.split("/", 1)
        try:
            min_stars = int(re.sub(r"[,\s]", "", parts[0].strip()))
        except Exception:
            min_stars = 10000
        language = parts[1].strip().lower() or None
    else:
        try:
            min_stars = int(re.sub(r"[,\s]", "", rest))
        except Exception:
            min_stars = 10000
    events = await _client.fetch_top_starred(min_stars=min_stars, language=language, limit=limit)
    return _events_to_dicts(events)


def _events_to_dicts(events) -> list[dict]:
    return [
        {
            "title": ev.title,
            "url": ev.url,
            "raw_content": ev.content,
            "external_id": ev.url,
            "published_at": ev.published_at,
            "author": ev.author,
        }
        for ev in events
    ]


# 向后兼容: GitHubFetcher.fetch(username, limit)
class GitHubFetcher:
    async def fetch(self, username: str, limit: int = 20) -> list[dict]:
        return await fetch(username, limit=limit)
