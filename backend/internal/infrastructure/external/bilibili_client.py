"""
BilibiliClient - 拉取 B 站 UP 主最新视频。

策略：
1) 优先使用 B 站官方 JSON API `api.bilibili.com/x/space/arc/search` + `x/web-interface/view`
2) 如果官方 API 被限流，fallback 到 RSSHub（需配置 rsshub_base_url）
3) 两种策略失败时，返回空列表（不会让上层报错）

注意：B 站官方 API 对匿名请求有较严格的 rate limit，建议并发 1，两次请求间间隔 1-2s。
"""
from __future__ import annotations

import re
import html
import datetime
import time
from dataclasses import dataclass

try:
    import httpx
    _HAS_HTTPX = True
except Exception:  # pragma: no cover
    httpx = None  # type: ignore
    _HAS_HTTPX = False

from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("bilibili_client")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass
class BilibiliVideo:
    title: str
    url: str
    content: str      # 视频简介/描述 + 标题，方便喂给摘要器
    published_at: datetime.datetime | None
    author: str = ""
    bvid: str = ""


class BilibiliClient:
    """Bilibili user video client. Supports both official API and RSSHub fallback."""

    def __init__(self, *, rsshub_base_url: str | None = None, request_interval: float = 1.5):
        self.rsshub_base_url = rsshub_base_url.rstrip("/") if rsshub_base_url else None
        self.request_interval = request_interval

    # ---------------- public ----------------
    async def list_videos(self, user_id: str, limit: int = 10) -> list[BilibiliVideo]:
        mid = str(user_id).strip()
        if not mid:
            return []
        if not _HAS_HTTPX:
            logger.warning("httpx not installed; returning empty list")
            return []

        # 策略 1: B 站官方 JSON API
        items = await self._list_via_official_api(mid, limit=limit)
        if items:
            logger.info("bilibili: official API returned %d videos for mid=%s", len(items), mid)
            return items

        # 策略 2: RSSHub fallback
        if self.rsshub_base_url:
            items = await self._list_via_rsshub(mid, limit=limit, kind="video")
            if items:
                logger.info("bilibili: RSSHub fallback returned %d videos for mid=%s", len(items), mid)
                return items

        logger.warning("bilibili: no videos available for mid=%s (official API blocked, RSSHub=%s)",
                       mid, "configured" if self.rsshub_base_url else "not configured")
        return []

    async def list_dynamics(self, user_id: str, limit: int = 10) -> list[BilibiliVideo]:
        mid = str(user_id).strip()
        if not mid or not _HAS_HTTPX:
            return []
        if not self.rsshub_base_url:
            # 动态流目前没有好的官方 JSON API，依赖 RSSHub
            logger.info("bilibili: list_dynamics skipped (no rsshub_base_url)")
            return []
        return await self._list_via_rsshub(mid, limit=limit, kind="dynamic")

    # ---------------- strategy 1: official API ----------------
    async def _list_via_official_api(self, mid: str, limit: int) -> list[BilibiliVideo]:
        """通过 B 站 space/arc/search + web-interface/view 拉视频。"""
        session_cls = httpx.AsyncClient if hasattr(httpx, "AsyncClient") else None
        if session_cls is None:
            return []

        results: list[BilibiliVideo] = []
        async with session_cls(timeout=30, follow_redirects=True, headers=dict(_DEFAULT_HEADERS)) as client:
            # 先做一次首页请求 —— 帮助拿到基础 cookie (buvid3, b_nut)
            try:
                await client.get("https://www.bilibili.com/")
                await async_sleep(0.3)
            except Exception:
                pass

            url = f"https://api.bilibili.com/x/space/arc/search?mid={mid}&pn=1&ps={max(limit, 10)}&order=pubdate"
            try:
                resp = await client.get(url, headers={"Referer": f"https://space.bilibili.com/{mid}/video"})
            except Exception as exc:
                logger.warning("bilibili official api network error: %s", exc)
                return []

            if resp.status_code != 200:
                logger.warning("bilibili official api status=%s", resp.status_code)
                return []

            try:
                j = resp.json()
            except Exception:
                return []

            code = int(j.get("code", -1)) if j.get("code") is not None else -1
            if code != 0:
                logger.warning("bilibili official api returned code=%s message=%s",
                               j.get("code"), str(j.get("message", ""))[:80])
                return []

            vlist = []
            try:
                vlist = j["data"]["list"]["vlist"]
            except Exception:
                pass

            for v in vlist[:limit]:
                title = str(v.get("title", "")).strip()
                bvid = str(v.get("bvid", "")).strip()
                author = str(v.get("author", "")).strip()
                description = str(v.get("description", "")).strip()
                ts = v.get("created", 0)
                published_at = None
                try:
                    if ts:
                        published_at = datetime.datetime.fromtimestamp(int(ts))
                except Exception:
                    pass

                url = f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://space.bilibili.com/{mid}"
                content = f"【{title}】\n{description}"
                results.append(BilibiliVideo(
                    title=title, url=url, content=content,
                    published_at=published_at, author=author, bvid=bvid,
                ))
                await async_sleep(self.request_interval)
        return results

    # ---------------- strategy 2: RSSHub ----------------
    async def _list_via_rsshub(self, mid: str, limit: int, kind: str = "video") -> list[BilibiliVideo]:
        if not self.rsshub_base_url:
            return []
        path = "video" if kind == "video" else "dynamic"
        url = f"{self.rsshub_base_url}/bilibili/user/{path}/{mid}"
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "DailyFeed/1.0"}) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                return _parse_rss_feed(resp.text, mid=mid, limit=limit)
        except Exception as exc:
            logger.warning("bilibili RSSHub fetch error: %s", exc)
            return []


# ---------------- helpers ----------------
import asyncio as _asyncio

async def async_sleep(seconds: float):
    try:
        await _asyncio.sleep(seconds)
    except Exception:
        time.sleep(seconds)


def _parse_rss_feed(xml_text: str, mid: str = "", limit: int = 10) -> list[BilibiliVideo]:
    if not xml_text:
        return []
    items: list[BilibiliVideo] = []
    for m in re.finditer(r"<item[^>]*>(.*?)</item>", xml_text, re.DOTALL):
        block = m.group(1)
        title = _tag_text(block, "title")
        url = _tag_text(block, "link")
        desc = _tag_text(block, "description")
        pub_date = _tag_text(block, "pubDate")
        author = _tag_text(block, "dc:creator") or _tag_text(block, "author")
        items.append(BilibiliVideo(
            title=title, url=url, content=_html_to_text(desc),
            published_at=_parse_date(pub_date), author=author or f"bilibili:{mid}",
        ))
        if len(items) >= limit:
            break
    if not items:
        for m in re.finditer(r"<entry[^>]*>(.*?)</entry>", xml_text, re.DOTALL):
            block = m.group(1)
            title = _tag_text(block, "title")
            url = _tag_attr(block, "link", "href")
            desc = _tag_text(block, "summary") or _tag_text(block, "content")
            updated = _tag_text(block, "updated") or _tag_text(block, "published")
            author = _tag_text(block, "author/name") or _tag_text(block, "name")
            items.append(BilibiliVideo(
                title=title, url=url, content=_html_to_text(desc),
                published_at=_parse_date(updated), author=author or f"bilibili:{mid}",
            ))
            if len(items) >= limit:
                break
    return items


def _tag_text(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
    return html.unescape(m.group(1)).strip() if m else ""


def _tag_attr(block: str, tag: str, attr: str) -> str:
    m = re.search(rf"<{tag}[^>]*{attr}\s*=\s*[\"']([^\"']+)[\"'][^>]*>", block, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _parse_date(text: str) -> datetime.datetime | None:
    if not text:
        return None
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in fmts:
        try:
            return datetime.datetime.strptime(text.strip(), fmt).replace(tzinfo=None)
        except Exception:
            continue
    return None


def _html_to_text(html_text: str) -> str:
    if not html_text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
