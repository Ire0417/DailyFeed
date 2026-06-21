"""
Bilibili fetcher - 拉取 UP 主最新视频。

基于 `internal.infrastructure.external.bilibili_client.BilibiliClient`（默认走 RSSHub）。
"""
from internal.infrastructure.monitoring.logger import get_logger
from internal.infrastructure.external.bilibili_client import BilibiliClient

logger = get_logger("bilibili_fetcher")

_client = BilibiliClient()


async def fetch(user_id: str, limit: int = 10) -> list[dict]:
    videos = await _client.list_videos(user_id, limit=limit)
    return [
        {
            "title": v.title,
            "url": v.url,
            "raw_content": v.content,
            "external_id": v.url,
            "published_at": v.published_at,
            "author": v.author,
        }
        for v in videos
    ]


async def fetch_dynamics(user_id: str, limit: int = 10) -> list[dict]:
    videos = await _client.list_dynamics(user_id, limit=limit)
    return [
        {
            "title": v.title,
            "url": v.url,
            "raw_content": v.content,
            "external_id": v.url,
            "published_at": v.published_at,
            "author": v.author,
        }
        for v in videos
    ]


# 向后兼容
class BilibiliFetcher:
    async def fetch(self, user_id: str, limit: int = 10) -> list[dict]:
        return await fetch(user_id, limit=limit)
