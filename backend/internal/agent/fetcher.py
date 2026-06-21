import time
import asyncio
from datetime import datetime, timedelta
from .base import BaseAgent
from internal.config.settings import settings
from internal.orchestrator.message_bus import message_bus, STREAM_SCHEDULE, STREAM_FETCH
from internal.orchestrator.registry import agent_registry
from internal.infrastructure.database.session import get_session
from internal.infrastructure.database.models import ContentModel
from internal.infrastructure.database.repositories.subscription_repo import SubscriptionRepository
from internal.infrastructure.database.repositories.content_repo import ContentRepository


from internal.pipeline.fetcher.factory import FetcherFactory
from internal.orchestrator.conversation_context import ensure_context, append_history

from internal.utils.hash_utils import fingerprint


class FetcherAgent(BaseAgent):
    """
    Fetcher agent. Consumes `schedule.triggered` events and, for each user,
    iterates their subscriptions, fetches new content, stores it in the DB,
    and emits `fetch.completed` events.
    """

    name = "fetcher"
    poll_interval_seconds = 10

    def __init__(self):
        super().__init__()
        self._streams = [STREAM_SCHEDULE]

    def process(self, stream: str, payload: dict):
        context = ensure_context(payload, default_next_agent="summarizer")
        event = payload.get("event")
        if event == "schedule.triggered":
            user_id = int(payload.get("user_id") or 0)
            if user_id <= 0:
                return None
            self._fetch_for_user(user_id, context)
            return {"ok": True, "user_id": user_id}
        return None

    async def _loop(self):
        last_heartbeat = 0.0
        while self._running:
            now = time.time()
            if now - last_heartbeat >= self.heartbeat_interval_seconds:
                agent_registry.heartbeat(self.name, status="running")
                last_heartbeat = now

            try:
                for stream in self._streams:
                    messages = message_bus.consume(
                        stream,
                        last_id=self._last_ids.get(stream),
                        count=10,
                        block_ms=100,
                    )
                    for msg in messages:
                        self._handle_message(stream, msg)
                        self._last_ids[stream] = msg["id"]
            except Exception as exc:
                self.logger.error("consume failed: %s", exc)

            await asyncio.sleep(self.poll_interval_seconds)

    # ---------- Fetching ----------
    def _fetch_for_user(self, user_id: int, context: dict):
        self.logger.info("fetcher: start for user_id=%d", user_id)
        since = datetime.utcnow() - timedelta(hours=settings.fetch_window_hours)

        total_new = 0
        subscription_count = 0
        content_ids: list[int] = []

        with get_session() as session:
            sub_repo = SubscriptionRepository(session)
            content_repo = ContentRepository(session)

            subscriptions = sub_repo.list_by_user(user_id=user_id, only_active=True)
            subscription_count = len(subscriptions)

            # emit started event (so observability can track progress)
            message_bus.emit_fetch_started(user_id=user_id, source_count=subscription_count, conversation=context)

            for sub in subscriptions:
                try:
                    new_ids = self._fetch_subscription(
                        session=session,
                        subscription=sub,
                        content_repo=content_repo,
                        since=since,
                    )
                    content_ids.extend(new_ids)
                    total_new += len(new_ids)
                    sub_repo.update_last_fetch(subscription_id=sub.id)
                except Exception as exc:
                    self.logger.error(
                        "fetch subscription failed sub_id=%d exc=%s",
                        sub.id, exc,
                    )

        append_history(
            context,
            agent=self.name,
            message=f"fetched {total_new} new items from {subscription_count} subscriptions",
            next_agent="summarizer",
            summary=f"fetch completed: {total_new} new contents",
            memo_updates={"content_ids": content_ids, "count": total_new},
        )
        task_id = (context.get("memo") or {}).get("task_id")
        if task_id:
            self.memory.log_step(
                task_id,
                "fetch",
                f"collected {total_new} contents",
                payload={"count": total_new},
                agent_name=self.name,
            )
        message_bus.emit_fetch_completed(
            user_id=user_id,
            content_ids=content_ids,
            count=total_new,
            conversation=context,
        )
        self.logger.info(
            "fetcher: done user_id=%d subscriptions=%d new_items=%d",
            user_id, subscription_count, total_new,
        )

    def _fetch_subscription(
        self,
        session,
        subscription,
        content_repo: ContentRepository,
        since: datetime,
    ) -> list[int]:
        fetcher = FetcherFactory.get(subscription.source_type)
        source_url = subscription.source_url

        # `fetcher.fetch` may be async
        import asyncio
        coro = fetcher.fetch(source_url, limit=20)
        if asyncio.iscoroutine(coro):
            items = asyncio.run(coro)
        else:
            items = coro

        new_ids: list[int] = []
        new_contents: list[ContentModel] = []
        seen = set()

        for item in items:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            content_text = (item.get("content") or "").strip()
            published_at = item.get("published_at") or datetime.utcnow()
            author = (item.get("author") or "").strip() or ""

            if not title or not url:
                continue

            # dedup by fingerprint
            fp = fingerprint(title, url)
            if fp in seen:
                continue
            seen.add(fp)

            # already-in-db dedup
            if content_repo.exists_by_hash(fp):
                continue

            # filter by time window
            if isinstance(published_at, datetime) and published_at < since:
                continue

            new_contents.append(ContentModel(
                subscription_id=subscription.id,
                title=title,
                author=author,
                raw_content=content_text,
                url=url,
                content_hash=fp,
                published_at=published_at,
                fetched_at=datetime.utcnow(),
            ))

        if new_contents:
            ids = []
            for c in new_contents:
                session.add(c)
                session.flush()
                ids.append(c.id)
            session.commit()
            new_ids.extend(ids)

        self.logger.info(
            "fetched subscription_id=%d type=%s total=%d new=%d",
            subscription.id, subscription.source_type,
            len(items), len(new_ids),
        )
        return new_ids
