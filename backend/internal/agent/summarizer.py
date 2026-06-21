"""
Summarizer Agent - 消费 fetch 事件，为新内容生成摘要。

根据 `settings.llm_enabled` 自动选择：
- LLM Summarizer (OpenAI / DeepSeek / Qwen)
- 或回退到抽取式摘要器

失败时：自动回退到抽取式；依然失败则记录日志，不阻断流程。
"""
import time
import asyncio
from datetime import datetime, timedelta
from .base import BaseAgent
from internal.config.settings import settings
from internal.orchestrator.message_bus import message_bus, STREAM_FETCH, STREAM_SUMMARY
from internal.orchestrator.registry import agent_registry
from internal.infrastructure.database.session import get_session
from internal.infrastructure.database.models import SummaryModel, ContentModel
from internal.infrastructure.database.repositories.content_repo import ContentRepository
from internal.infrastructure.database.repositories.summary_repo import SummaryRepository
from internal.pipeline.summarizer import get_summarizer, LLMResult
from internal.pipeline.summarizer.provider import build_provider
from internal.infrastructure.monitoring.logger import get_logger
from internal.infrastructure.monitoring import metrics
from internal.orchestrator.conversation_context import ensure_context, append_history

logger = get_logger("summarizer_agent")


class SummarizerAgent(BaseAgent):
    name = "summarizer"
    poll_interval_seconds = 10

    def __init__(self):
        super().__init__()
        self._streams = [STREAM_FETCH]
        self._summarizer = get_summarizer()
        self._system_prompt = "请你把给定的多条内容精简成 5 句话的摘要"
        self._provider = self._build_provider()

    def process(self, stream: str, payload: dict):
        context = ensure_context(payload, default_next_agent="aggregator")
        event = payload.get("event")
        if event == "fetch.completed":
            user_id = int(payload.get("user_id") or 0)
            content_ids = payload.get("content_ids") or []
            if user_id <= 0 and not content_ids:
                return None
            self._summarize_pending(user_id=user_id, content_ids=content_ids, context=context)
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
                logger.error("consume failed: %s", exc)

            await asyncio.sleep(self.poll_interval_seconds)

    # -------- Summarization --------
    def _summarize_pending(self, user_id: int, content_ids: list[int], context: dict):
        logger.info("summarizer: start user_id=%d provider=%s",
                    user_id, getattr(self._summarizer, "provider", None))
        new_ids: list[int] = []
        total = 0

        with get_session() as session:
            content_repo = ContentRepository(session)
            summary_repo = SummaryRepository(session)

            if content_ids:
                q = session.query(ContentModel).filter(ContentModel.id.in_(content_ids))
                contents = q.all()
                already = {
                    s.content_id
                    for s in session.query(SummaryModel).filter(
                        SummaryModel.content_id.in_([c.id for c in contents])
                    ).all()
                }
                contents = [c for c in contents if c.id not in already]
            else:
                since = datetime.utcnow() - timedelta(hours=settings.fetch_window_hours * 2)
                contents = content_repo.get_pending_summary(since=since, limit=200)

            total = len(contents)
            metrics.gauge("summarizer.pending_items", total)
            message_bus.emit_summary_started(user_id=user_id, content_count=total, conversation=context)

            for content in contents:
                try:
                    start = time.perf_counter()
                    result = self._run_sync(content, context)
                    ms = int((time.perf_counter() - start) * 1000)
                    summary = SummaryModel(
                        content_id=content.id,
                        summary_text=result.summary,
                        generated_by=result.provider,
                        tokens_used=result.tokens_total,
                        duration_ms=result.duration_ms,
                        generated_at=datetime.utcnow(),
                    )
                    created = summary_repo.create(summary)
                    new_ids.append(created.id)
                    metrics.timing_ms(f"summarizer.item.{result.provider}", ms)
                    metrics.counter("summarizer.items_done", 1)
                except Exception as exc:
                    logger.error(
                        "summarize failed content_id=%d exc=%s",
                        content.id, exc,
                    )
                    metrics.counter("summarizer.items_failed", 1)

        append_history(
            context,
            agent=self.name,
            message=f"summarized {len(new_ids)} contents",
            next_agent="aggregator",
            summary=f"generated {len(new_ids)} summaries",
            memo_updates={"summary_ids": new_ids, "summary_count": len(new_ids)},
        )
        task_id = (context.get("memo") or {}).get("task_id")
        if task_id:
            self.memory.log_step(
                task_id,
                "summarize",
                f"generated {len(new_ids)} summaries",
                payload={"summary_ids": new_ids[:20]},
                agent_name=self.name,
            )
        message_bus.emit_summary_completed(
            user_id=user_id,
            summary_ids=new_ids,
            count=len(new_ids),
            conversation=context,
        )
        logger.info(
            "summarizer: done user_id=%d total=%d summarized=%d",
            user_id, total, len(new_ids),
        )

    def _run_sync(self, content: ContentModel, context: dict) -> LLMResult:
        if self._provider:
            messages = [
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"history={context.get('history', [])}\n"
                        f"title={content.title or ''}\n"
                        f"body={(content.raw_content or '')[:8000]}"
                    ),
                },
            ]
            loop = asyncio.new_event_loop()
            try:
                raw = loop.run_until_complete(
                    self._provider.call(messages, max_tokens=settings.llm_max_tokens, temperature=0.2)
                )
                if raw.ok:
                    return LLMResult(
                        summary=raw.text,
                        provider=raw.provider,
                        model=raw.model,
                        tokens_in=raw.tokens_in,
                        tokens_out=raw.tokens_out,
                        tokens_total=raw.tokens_total,
                        duration_ms=raw.duration_ms,
                    )
            except Exception:
                pass
            finally:
                loop.close()

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._summarizer.summarize(
                    content.raw_content or "",
                    title=content.title or "",
                    source=content.source_type or "unknown",
                )
            )
        finally:
            loop.close()

    def _build_provider(self):
        if not settings.llm_enabled:
            return None
        try:
            return build_provider(
                provider_name=settings._resolved_llm_provider,
                api_key=settings._resolved_llm_api_key,
                base_url=settings.llm_base_url,
                model=settings._resolved_llm_model,
                timeout=settings.llm_timeout_seconds,
            )
        except Exception:
            return None
