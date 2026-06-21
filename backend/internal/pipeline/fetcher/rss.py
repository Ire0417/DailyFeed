"""
RSS fetcher - fetch feeds from a given URL.

Phase 1 MVP uses `feedparser` when available, with graceful degradation to
a simple regex-based parser for resilience.
"""
import re
import html
from datetime import datetime
from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("rss_fetcher")

try:
    import feedparser
    _HAS_FEEDPARSER = True
except Exception:
    feedparser = None
    _HAS_FEEDPARSER = False

try:
    import urllib.request as _url
    _HAS_URLLIB = True
except Exception:
    _HAS_URLLIB = False


def _fetch_raw(url: str, timeout: int = 15) -> str:
    if not _HAS_URLLIB:
        raise RuntimeError("urllib not available")
    req = _url.Request(
        url,
        headers={
            "User-Agent": "DailyFeed/0.1 (+https://dailyfeed.local)",
            "Accept": "application/rss+xml, application/atom+xml, text/xml",
        },
    )
    with _url.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        # decode with best-effort charset detection
        charset = "utf-8"
        content_type = resp.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w\-]+)", content_type)
        if m:
            charset = m.group(1)
        try:
            return data.decode(charset, errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")


def _parse_with_feedparser(xml_text: str) -> list[dict]:
    if not _HAS_FEEDPARSER:
        return []
    doc = feedparser.parse(xml_text)
    items = []
    for entry in getattr(doc, "entries", []) or []:
        title = _clean(getattr(entry, "title", "") or "")
        link = getattr(entry, "link", "") or ""
        content_html = ""
        if getattr(entry, "content", None):
            for c in entry.content:
                content_html += getattr(c, "value", "") or ""
        if not content_html:
            content_html = getattr(entry, "description", "") or ""
        summary = getattr(entry, "summary", "") or ""
        published = None
        for key in ("published_parsed", "updated_parsed"):
            t = getattr(entry, key, None)
            if t:
                try:
                    published = datetime(*t[:6])
                    break
                except Exception:
                    pass
        content_text = _html_to_text(content_html or summary)
        items.append({
            "title": title,
            "url": link,
            "content": content_text,
            "published_at": published,
            "author": "",
        })
    return items


def _parse_fallback(xml_text: str) -> list[dict]:
    items = []
    # Match RSS <item> or Atom <entry> blocks.
    for pattern, title_tag, link_tag, desc_tag, pub_tag in [
        (r"<item[^>]*>(.*?)</item>", "title", "link", "description", "pubDate"),
        (r"<entry[^>]*>(.*?)</entry>", "title", "link", "summary", "updated"),
    ]:
        for match in re.finditer(pattern, xml_text, re.DOTALL | re.IGNORECASE):
            block = match.group(1)
            title = _tag_text(block, title_tag)
            link = _tag_text(block, link_tag)
            if not link:
                # Try href attribute
                hm = re.search(r'href\s*=\s*"([^"]+)"', block, re.IGNORECASE)
                if hm:
                    link = hm.group(1)
            desc = _tag_text(block, desc_tag)
            pub_text = _tag_text(block, pub_tag)
            published = _parse_date(pub_text)
            content_text = _html_to_text(desc)
            items.append({
                "title": _clean(title),
                "url": link.strip(),
                "content": content_text,
                "published_at": published,
                "author": "",
            })
    return items


def _tag_text(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    return html.unescape(m.group(1)).strip()


def _parse_date(text: str) -> datetime | None:
    if not text:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=None)
        except Exception:
            continue
    return None


def _html_to_text(html_text: str) -> str:
    if not html_text:
        return ""
    # Remove scripts/styles
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode entities
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean(text: str) -> str:
    return _html_to_text(text)


class RSSFetcher:
    async def fetch(self, url: str, limit: int = 20):
        """
        Fetch an RSS/Atom feed and return a list of item dicts:
            {title, url, content, published_at, author}
        """
        try:
            xml_text = _fetch_raw(url)
        except Exception as exc:
            logger.error("fetch failed url=%s exc=%s", url, exc)
            return []

        items = _parse_with_feedparser(xml_text) or _parse_fallback(xml_text)
        # Sort by published_at descending, keep limit
        items_with_time = [it for it in items if it.get("published_at")]
        items_without_time = [it for it in items if not it.get("published_at")]
        items_with_time.sort(key=lambda it: it["published_at"], reverse=True)
        merged = items_with_time + items_without_time
        return merged[:limit]
