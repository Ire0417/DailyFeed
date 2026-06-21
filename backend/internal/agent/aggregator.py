import time
import asyncio
from datetime import datetime, date, timedelta
from .base import BaseAgent
from internal.config.settings import settings
from internal.orchestrator.message_bus import message_bus, STREAM_SUMMARY, STREAM_AGGREGATE
from internal.orchestrator.registry import agent_registry
from internal.infrastructure.database.session import get_session
from internal.infrastructure.database.models import (
    ReportModel,
    SubscriptionModel,
    ContentModel,
    SummaryModel,
    UserModel,
)
from internal.infrastructure.database.repositories.report_repo import ReportRepository
from internal.infrastructure.database.repositories.user_repo import UserRepository
from internal.pipeline.aggregator.report_builder import ReportBuilder
from internal.orchestrator.conversation_context import ensure_context, append_history


class AggregatorAgent(BaseAgent):
    """
    Aggregator agent. Consumes `summary.completed` events, collects all
    recent summaries for a user, builds a Markdown/HTML report, stores it
    in the DB, and emits `aggregate.completed`.
    """

    name = "aggregator"
    poll_interval_seconds = 10

    def __init__(self):
        super().__init__()
        self._streams = [STREAM_SUMMARY]
        self._builder = ReportBuilder()

    def process(self, stream: str, payload: dict):
        context = ensure_context(payload, default_next_agent="pusher")
        event = payload.get("event")
        if event == "summary.completed":
            user_id = int(payload.get("user_id") or 0)
            if user_id <= 0:
                return None
            self._aggregate(user_id, context)
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

    # ---------- Aggregation ----------
    def _aggregate(self, user_id: int, context: dict):
        self.logger.info("aggregator: start user_id=%d", user_id)
        report_id = None

        message_bus.emit_aggregate_started(user_id=user_id, conversation=context)

        with get_session() as session:
            report_repo = ReportRepository(session)
            user_repo = UserRepository(session)

            # Avoid duplicates: one report per user per day
            today = date.today()
            existing = report_repo.get_by_date(user_id=user_id, report_date=today)
            if existing:
                self.logger.info(
                    "report already exists for user_id=%d date=%s, re-using",
                    user_id, today,
                )
                report_id = existing.id

            # Fetch: content + summary for user
            since = datetime.utcnow() - timedelta(hours=settings.fetch_window_hours * 2)
            rows = (
                session.query(
                    SubscriptionModel, ContentModel, SummaryModel,
                )
                .join(ContentModel, ContentModel.subscription_id == SubscriptionModel.id)
                .join(SummaryModel, SummaryModel.content_id == ContentModel.id)
                .filter(SubscriptionModel.user_id == user_id)
                .filter(ContentModel.published_at >= since)
                .order_by(ContentModel.published_at.desc())
                .limit(500)
                .all()
            )

            # Group by subscription source
            grouped: dict[str, list[dict]] = {}
            for sub, content, summary in rows:
                label = f"{sub.source_type}: {sub.source_url[:40]}"
                grouped.setdefault(label, []).append({
                    "title": content.title,
                    "url": content.url,
                    "summary": summary.summary_text,
                    "published_at": content.published_at,
                    "author": content.author,
                })

            # Build report body
            report_data = asyncio.run(self._builder.build(grouped))
            user = user_repo.get_by_id(user_id)

            if existing:
                existing.markdown_body = report_data["markdown_body"]
                existing.html_body = report_data["html_body"]
                existing.title = report_data["title"]
                existing.stats = report_data["stats"]
                existing.status = "ready"
                session.commit()
                report_id = existing.id
            else:
                report = ReportModel(
                    user_id=user_id,
                    report_date=today,
                    title=report_data["title"],
                    markdown_body=report_data["markdown_body"],
                    html_body=report_data["html_body"],
                    stats=report_data["stats"],
                    status="ready",
                    created_at=datetime.utcnow(),
                )
                created = report_repo.create(report)
                report_id = created.id

        append_history(
            context,
            agent=self.name,
            message=f"aggregated report_id={report_id or 0}",
            next_agent="pusher",
            summary=f"report ready: {report_id or 0}",
            memo_updates={"report_id": report_id or 0},
        )
        task_id = (context.get("memo") or {}).get("task_id")
        if task_id:
            self.memory.log_step(
                task_id,
                "aggregate",
                f"generated report {report_id or 0}",
                payload={"report_id": report_id or 0},
                agent_name=self.name,
            )
        message_bus.emit_aggregate_completed(
            user_id=user_id,
            report_id=report_id or 0,
            conversation=context,
        )
        self.logger.info(
            "aggregator: done user_id=%d report_id=%d",
            user_id, report_id,
        )
