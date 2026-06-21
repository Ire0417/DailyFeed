"""
GitHubClient - 拉取用户 / 仓库的公开动态。

默认使用 GitHub 的 Atom feed（无需 token，匿名，有限频）：
    https://github.com/{username}.atom           -> 用户动态
    https://github.com/{owner}/{repo}/releases.atom -> 仓库 Release

有 token 时（可选）自动加 Authorization 头，提升速率限制。
"""
from __future__ import annotations

import re
import html
import datetime
from dataclasses import dataclass
from typing import Iterable

try:
    import httpx
    _HAS_HTTPX = True
except Exception:  # pragma: no cover
    httpx = None  # type: ignore
    _HAS_HTTPX = False

from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("github_client")


@dataclass
class GitHubEvent:
    title: str
    url: str
    content: str
    published_at: datetime.datetime | None
    author: str = ""


class GitHubClient:
    """Simple GitHub public activity client."""

    FEED_TIMEOUT = 15

    def __init__(self, token: str | None = None, *, base_url: str = "https://github.com"):
        self.token = token
        self.base_url = base_url.rstrip("/")

    # ---------- internal helpers ----------
    def _build_client(self, *, timeout: int | None = None) -> "httpx.AsyncClient":
        """Build httpx.AsyncClient; on Windows we sometimes need verify=False."""
        return httpx.AsyncClient(timeout=timeout or self.FEED_TIMEOUT, follow_redirects=True)

    async def _get_text(self, url: str, *, headers: dict[str, str] | None = None,
                        params: dict | None = None, timeout: int | None = None) -> str | None:
        """GET a URL with auto-SSL fallback for Windows/misconfigured Python environments."""
        headers = headers or {}
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        try:
            async with self._build_client(timeout=timeout) as client:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    logger.warning("github http=%s url=%s", resp.status_code, url)
                    return None
                return resp.text
        except Exception as exc:  # pragma: no cover
            exc_str = str(exc).lower()
            ssl_related = any(k in exc_str for k in ("ssl", "certificate", "verify failed", "cert_verify"))
            if ssl_related:
                logger.warning("github SSL error (%s), retrying with verify=False", exc)
                try:
                    async with httpx.AsyncClient(
                        timeout=timeout or self.FEED_TIMEOUT,
                        follow_redirects=True,
                        verify=False,
                    ) as client:
                        resp = await client.get(url, headers=headers, params=params)
                        if resp.status_code != 200:
                            logger.warning("github retry http=%s url=%s", resp.status_code, url)
                            return None
                        return resp.text
                except Exception as exc2:  # pragma: no cover
                    logger.error("github retry failed: %s", exc2)
                    return None
            logger.error("github request failed url=%s exc=%s", url, exc)
            return None

    async def _get_json(self, url: str, *, headers: dict[str, str] | None = None,
                        params: dict | None = None, timeout: int | None = None) -> dict | None:
        text = await self._get_text(url, headers=headers, params=params, timeout=timeout)
        if text is None:
            return None
        try:
            import json as _json
            return _json.loads(text)
        except Exception as exc:  # pragma: no cover
            logger.error("github non-JSON response: %s", exc)
            return None

    # -------- Public API --------
    async def list_events(self, username: str, limit: int = 20) -> list[GitHubEvent]:
        """Return the latest activity items for a GitHub user."""
        if not _HAS_HTTPX:
            logger.warning("httpx not installed; returning empty list")
            return []

        username = username.strip()
        if not username:
            return []

        url = f"{self.base_url}/{username}.atom"
        headers = {
            "User-Agent": "DailyFeed/1.0",
            "Accept": "application/atom+xml,application/xml;q=0.9",
        }

        raw = await self._get_text(url, headers=headers)
        if not raw:
            return []

        items = _parse_atom(raw)
        for ev in items:
            if not ev.author:
                ev.author = username
        return items[:limit]

    async def list_releases(self, owner: str, repo: str, limit: int = 10) -> list[GitHubEvent]:
        """Return the latest releases for owner/repo."""
        if not _HAS_HTTPX:
            return []
        url = f"{self.base_url}/{owner}/{repo}/releases.atom"
        headers = {"User-Agent": "DailyFeed/1.0"}
        raw = await self._get_text(url, headers=headers)
        if not raw:
            return []
        return _parse_atom(raw)[:limit]

    # ==================== NEW: Trending & Top-Starred ====================

    async def fetch_trending(
        self,
        since: str = "daily",
        language: str | None = None,
        limit: int = 10,
    ) -> list[GitHubEvent]:
        """
        Fetch the GitHub Trending page.

        Args:
            since: "daily" | "weekly" | "monthly"
            language: e.g. "python" / "typescript" / None (all)
            limit:    max items to return
        """
        if not _HAS_HTTPX:
            return []
        since = (since or "daily").lower()
        if since not in ("daily", "weekly", "monthly"):
            since = "daily"

        # /trending/python?since=daily
        lang_segment = f"/{language.strip().lower()}" if language and language.strip() else ""
        url = f"{self.base_url}/trending{lang_segment}?since={since}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        raw_html = await self._get_text(url, headers=headers, timeout=30)
        if not raw_html:
            return []

        items = _parse_trending_html(raw_html)
        for ev in items:
            if not ev.author:
                ev.author = "GitHub Trending"
        logger.info("github trending parsed %d items (since=%s, lang=%s)", len(items), since, language)
        return items[:limit]

    async def fetch_top_starred(
        self,
        min_stars: int = 10000,
        language: str | None = None,
        limit: int = 10,
    ) -> list[GitHubEvent]:
        """
        Fetch the all-time top-starred repositories via GitHub Search API.

        Args:
            min_stars: minimum number of stars (default 10000).
            language:  e.g. "python" / "typescript" / None (all)
            limit:     max items to return (Search API max 100)
        """
        if not _HAS_HTTPX:
            return []
        q = f"stars:>{min_stars}"
        if language and language.strip():
            q += f" language:{language.strip().lower()}"

        url = "https://api.github.com/search/repositories"
        params = {"q": q, "sort": "stars", "order": "desc", "per_page": max(1, min(limit, 100))}
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "DailyFeed/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        data = await self._get_json(url, headers=headers, params=params, timeout=30)
        if not data:
            return []

        items: list[GitHubEvent] = []
        for repo in data.get("items", [])[:limit]:
            owner = repo.get("owner", {}) or {}
            login = owner.get("login", "")
            full_name = repo.get("full_name") or f"{login}/"
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language") or "—"
            description = repo.get("description") or ""
            url = repo.get("html_url") or f"{self.base_url}/{full_name}"

            title = f"{full_name} ⭐{stars:,} [{lang}]"
            content_parts = [
                f"项目: {full_name}",
                f"描述: {description}",
                f"Star 数: {stars:,}",
                f"语言: {lang}",
            ]
            if repo.get("homepage"):
                content_parts.append(f"主页: {repo['homepage']}")
            if repo.get("topics"):
                content_parts.append(f"标签: {', '.join(repo['topics'][:5])}")

            items.append(GitHubEvent(
                title=title,
                url=url,
                content="\n".join(content_parts),
                published_at=datetime.datetime.now(),
                author=login or "github",
            ))

        logger.info("github top-starred parsed %d items (min_stars=%s, lang=%s)", len(items), min_stars, language)
        return items


# -------- Atom parsing (lightweight) --------
def _parse_atom(xml_text: str) -> list[GitHubEvent]:
    if not xml_text:
        return []

    items: list[GitHubEvent] = []
    for m in re.finditer(r"<entry[^>]*>(.*?)</entry>", xml_text, re.DOTALL):
        block = m.group(1)
        title = _tag_text(block, "title")
        url = _tag_attr(block, "link", "href")
        updated = _tag_text(block, "updated")
        summary = _tag_text(block, "summary")
        author = _tag_text(block, "author/name") or _tag_text(block, "name")

        content_html = _tag_text(block, "content") or summary
        content_text = _html_to_text(content_html)

        published_at = None
        if updated:
            try:
                published_at = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass

        items.append(GitHubEvent(
            title=title,
            url=url,
            content=content_text,
            published_at=published_at,
            author=author,
        ))
    return items


def _tag_text(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
    return html.unescape(m.group(1)).strip() if m else ""


def _tag_attr(block: str, tag: str, attr: str) -> str:
    m = re.search(rf"<{tag}[^>]*{attr}\s*=\s*[\"']([^\"']+)[\"'][^>]*>", block, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _html_to_text(html_text: str) -> str:
    if not html_text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# -------- Trending HTML parsing --------
def _parse_trending_html(raw_html: str) -> list[GitHubEvent]:
    """
    Parse the GitHub /trending HTML page into a list of GitHubEvent items.
    We look for every <article class="Box-row"> which represents one repository entry.
    """
    if not raw_html:
        return []

    items: list[GitHubEvent] = []
    # Split by article boxes (GitHub uses <article class="Box-row"> entries)
    for block in re.finditer(r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>',
                             raw_html, flags=re.DOTALL | re.IGNORECASE):
        entry = block.group(1)

        # Owner / repo: look for first <h2><a href="/owner/repo">
        m = re.search(r'<h2[^>]*>.*?<a[^>]*href="/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)"',
                      entry, flags=re.DOTALL | re.IGNORECASE)
        if not m:
            # Try a looser fallback: any <a href="/owner/repo"> inside the article
            m = re.search(r'<a[^>]*href="/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)"', entry,
                          flags=re.IGNORECASE)
            if not m:
                continue
        owner = m.group(1)
        repo = m.group(2)
        full_name = f"{owner}/{repo}"
        url = f"https://github.com/{full_name}"

        # Description: <p class="col-9 color-fg-muted ...">...</p>
        description = ""
        m_desc = re.search(r'<p[^>]*class="[^"]*(?:col-9|pr-4)[^"]*"[^>]*>(.*?)</p>',
                           entry, flags=re.DOTALL | re.IGNORECASE)
        if m_desc:
            description = _html_to_text(m_desc.group(1))

        # Language: <span itemprop="programmingLanguage">Python</span>
        language = ""
        m_lang = re.search(r'<span[^>]*itemprop="programmingLanguage"[^>]*>([^<]+)</span>',
                           entry, flags=re.IGNORECASE)
        if m_lang:
            language = html.unescape(m_lang.group(1)).strip()

        # Total stars: the first <a href="/owner/repo/stargazers"> inside the article
        total_stars = 0
        m_stars = re.search(rf'href="/{re.escape(owner)}/{re.escape(repo)}/stargazers"[^>]*>([^<]+)</a>',
                            entry, flags=re.IGNORECASE)
        if not m_stars:
            # fallback: look for "stargazers" link text
            m_stars = re.search(r'<a[^>]*href="[^"]*/stargazers"[^>]*>([^<]+)</a>',
                                entry, flags=re.IGNORECASE)
        if m_stars:
            try:
                total_stars = int(re.sub(r"[,\s]", "", html.unescape(m_stars.group(1)).strip()))
            except Exception:
                total_stars = 0

        # "Today" / period stars: trailing text like "1,234 stars today"
        period_stars = 0
        m_period = re.search(r'([\d,]+)\s*stars?\s*(today|this\s*week|this\s*month)?',
                             entry, flags=re.IGNORECASE)
        if m_period:
            try:
                period_stars = int(re.sub(r"[,\s]", "", m_period.group(1)))
            except Exception:
                period_stars = 0

        title_parts = [full_name]
        if language:
            title_parts.append(f"[{language}]")
        if total_stars:
            title_parts.append(f"⭐{total_stars:,}")
        if period_stars:
            title_parts.append(f"(+{period_stars:,} this period)")
        title = " ".join(title_parts)

        content_lines = [
            f"项目: {full_name}",
        ]
        if description:
            content_lines.append(f"描述: {description}")
        if language:
            content_lines.append(f"语言: {language}")
        if total_stars:
            content_lines.append(f"总 Star: {total_stars:,}")
        if period_stars:
            content_lines.append(f"本期新增 Star: {period_stars:,}")
        content = "\n".join(content_lines)

        items.append(GitHubEvent(
            title=title,
            url=url,
            content=content,
            published_at=datetime.datetime.now(),
            author=owner,
        ))
    return items
