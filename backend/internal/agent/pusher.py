import time
import asyncio
from datetime import datetime
from .base import BaseAgent
from internal.config.settings import settings
from internal.orchestrator.message_bus import message_bus, STREAM_AGGREGATE, STREAM_PUSH
from internal.orchestrator.registry import agent_registry
from internal.infrastructure.database.session import get_session
from internal.infrastructure.database.models import UserModel
from internal.infrastructure.database.repositories.report_repo import ReportRepository
from internal.infrastructure.database.repositories.user_repo import UserRepository
from internal.pipeline.pusher.notifier import Notifier
from internal.pipeline.summarizer.provider import build_provider
from internal.orchestrator.conversation_context import ensure_context, append_history


class PusherAgent(BaseAgent):
    """
    Pusher agent. Consumes `aggregate.completed` events and pushes the
    generated report to each user's configured channels (email, wechat,
    dingtalk). Logs push status to push_logs.
    """

    name = "pusher"
    poll_interval_seconds = 10

    def __init__(self):
        super().__init__()
        self._streams = [STREAM_AGGREGATE]
        self._system_prompt = "请你把摘要写成邮件正文，语气要亲切，不要用 Markdown"
        self._provider = self._build_provider()

    def process(self, stream: str, payload: dict):
        context = ensure_context(payload, default_next_agent="done")
        event = payload.get("event")
        if event == "aggregate.completed":
            user_id = int(payload.get("user_id") or 0)
            report_id = int(payload.get("report_id") or 0)
            if user_id <= 0 or report_id <= 0:
                return None
            self._push(user_id, report_id, context)
            return {"ok": True, "user_id": user_id, "report_id": report_id}
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

    # ---------- Push ----------
    def _push(self, user_id: int, report_id: int, context: dict):
        self.logger.info("pusher: start user_id=%d report_id=%d", user_id, report_id)

        with get_session() as session:
            report_repo = ReportRepository(session)
            report = report_repo.get_by_id(report_id=report_id, user_id=user_id)
            if not report:
                self.logger.error("report not found: %d", report_id)
                return

            user = session.query(UserModel).filter(UserModel.id == user_id).first()
            if not user:
                self.logger.error("user not found: %d", user_id)
                return

            # Default channels (email first if we have email)
            user_settings = user.settings or {}
            channels = user_settings.get("channels") or ["email"]
            email_recipients = user_settings.get("email_recipients") or [user.email]

            notifier = Notifier(channels)
            push_content = self._email_body_from_summary(
                report.title,
                report.markdown_body or "",
                context,
            )
            results = asyncio.run(
                notifier.notify(
                    title=report.title,
                    content=push_content,
                    html_body=report.html_body,
                    email_recipients=email_recipients,
                )
            )

            # Push event for observability + push logs
            for ch, ok in results.items():
                message_bus.emit_push_started(
                    user_id=user_id,
                    report_id=report_id,
                    channel=ch,
                    conversation=context,
                )
                message_bus.emit_push_completed(
                    user_id=user_id,
                    report_id=report_id,
                    channel=ch,
                    status="delivered" if ok else "failed",
                    conversation=context,
                )
                report_repo.add_push_log(
                    report_id=report_id,
                    channel=ch,
                    status=("delivered" if ok else "failed"),
                    error_message=None if ok else f"channel {ch} returned not ok",
                )

            # Mark report delivered (if any channel succeeded)
            if any(results.values()):
                report_repo.update_status(report_id=report_id, status="delivered")

        append_history(
            context,
            agent=self.name,
            message=f"pushed report={report_id} channels={list(results.keys())}",
            next_agent="done",
            summary="pipeline completed",
            memo_updates={"push_results": results},
        )
        task_id = (context.get("memo") or {}).get("task_id")
        if task_id:
            self.memory.log_step(
                task_id,
                "push",
                f"push completed {results}",
                payload={"results": results},
                agent_name=self.name,
            )
        if user_id > 0:
            self.memory.remember_long_term(
                kind=self._memory_kind_for_result(),
                content=f"report {report_id} pushed with results={results}",
                user_id=user_id,
                tags=["pusher", "delivery"],
                agent_name=self.name,
            )

        self.logger.info("pusher: done user_id=%d report_id=%d results=%s", user_id, report_id, results)

    def _email_body_from_summary(self, title: str, summary_text: str, context: dict) -> str:
        if not self._provider:
            return summary_text
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"history={context.get('history', [])}\n"
                    f"title={title}\n"
                    f"summary={summary_text[:6000]}"
                ),
            },
        ]
        loop = asyncio.new_event_loop()
        try:
            resp = loop.run_until_complete(
                self._provider.call(messages, max_tokens=settings.llm_max_tokens, temperature=0.4)
            )
            if resp.ok and resp.text:
                return resp.text
            return summary_text
        except Exception:
            return summary_text
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
