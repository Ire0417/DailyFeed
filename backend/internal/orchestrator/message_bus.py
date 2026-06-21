import json
import time
from datetime import datetime
from internal.infrastructure.cache.redis_client import redis_client
from internal.infrastructure.monitoring.logger import get_logger
from internal.orchestrator.conversation_context import new_context

logger = get_logger("message_bus")

# Stream (topic) definitions
STREAM_SCHEDULE = "stream:schedule"
STREAM_FETCH = "stream:fetch"
STREAM_SUMMARY = "stream:summary"
STREAM_AGGREGATE = "stream:aggregate"
STREAM_PUSH = "stream:push"
STREAM_SYSTEM = "stream:system"

ALL_STREAMS = [
    STREAM_SCHEDULE,
    STREAM_FETCH,
    STREAM_SUMMARY,
    STREAM_AGGREGATE,
    STREAM_PUSH,
    STREAM_SYSTEM,
]


class MessageBus:
    """
    Lightweight pub/sub message bus. Backed by Redis Stream when
    available; falls back to an in-memory queue so the system can
    still run in development / single-node mode.

    Usage:
        bus = MessageBus()
        bus.publish("stream:fetch", {"user_id": 1, "trigger": "cron"})

        while True:
            messages = bus.consume("stream:fetch", last_id)
            for m in messages:
                handle(m)
                last_id = m["id"]
    """

    def __init__(self):
        self.redis = redis_client
        self._last_ids: dict[str, str] = {}

    # ---------- Publish ----------
    def publish(self, stream: str, payload: dict) -> str | None:
        fields = {
            "ts": str(int(time.time() * 1000)),
            "payload": json.dumps(payload, ensure_ascii=False),
        }
        try:
            msg_id = self.redis.xadd(stream, fields)
        except Exception as exc:
            logger.warning("publish failed stream=%s exc=%s", stream, exc)
            return None

        logger.info(
            "pushed to stream=%s id=%s payload_keys=%s",
            stream,
            msg_id,
            list(payload.keys()),
        )
        return msg_id

    # ---------- Consume ----------
    def consume(self, stream: str, last_id: str | None = None, count: int = 10, block_ms: int = 500):
        read_id = last_id or self._last_ids.get(stream) or "0"
        try:
            result = self.redis.xread({stream: read_id}, count=count, block_ms=block_ms)
        except Exception as exc:
            logger.warning("consume failed stream=%s exc=%s", stream, exc)
            return []

        messages = []
        for raw in result.get(stream, []):
            msg_id = raw["id"]
            payload_raw = raw["fields"].get("payload")
            try:
                payload = json.loads(payload_raw) if payload_raw else {}
            except Exception:
                payload = {}

            messages.append({"id": msg_id, "payload": payload})
            self._last_ids[stream] = msg_id

        return messages

    # ---------- Convenience event publishers ----------
    def emit_schedule_triggered(self, user_id: int = 0, conversation: dict | None = None):
        ctx = conversation or new_context(
            user_id=user_id,
            plan="scheduler trigger -> fetch -> summarize -> aggregate -> push",
            next_agent="fetcher",
        )
        return self.publish(
            STREAM_SCHEDULE,
            {
                "event": "schedule.triggered",
                "user_id": user_id,
                "conversation": ctx,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_fetch_started(self, user_id: int, source_count: int, conversation: dict | None = None):
        return self.publish(
            STREAM_FETCH,
            {
                "event": "fetch.started",
                "user_id": user_id,
                "source_count": source_count,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_fetch_completed(
        self,
        user_id: int,
        content_ids: list[int],
        count: int,
        conversation: dict | None = None,
    ):
        return self.publish(
            STREAM_FETCH,
            {
                "event": "fetch.completed",
                "user_id": user_id,
                "content_ids": content_ids,
                "count": count,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_summary_started(self, user_id: int, content_count: int, conversation: dict | None = None):
        return self.publish(
            STREAM_SUMMARY,
            {
                "event": "summary.started",
                "user_id": user_id,
                "content_count": content_count,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_summary_completed(
        self,
        user_id: int,
        summary_ids: list[int],
        count: int,
        conversation: dict | None = None,
    ):
        return self.publish(
            STREAM_SUMMARY,
            {
                "event": "summary.completed",
                "user_id": user_id,
                "summary_ids": summary_ids,
                "count": count,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_aggregate_started(self, user_id: int, conversation: dict | None = None):
        return self.publish(
            STREAM_AGGREGATE,
            {
                "event": "aggregate.started",
                "user_id": user_id,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_aggregate_completed(self, user_id: int, report_id: int, conversation: dict | None = None):
        return self.publish(
            STREAM_AGGREGATE,
            {
                "event": "aggregate.completed",
                "user_id": user_id,
                "report_id": report_id,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_push_started(
        self,
        user_id: int,
        report_id: int,
        channel: str,
        conversation: dict | None = None,
    ):
        return self.publish(
            STREAM_PUSH,
            {
                "event": "push.started",
                "user_id": user_id,
                "report_id": report_id,
                "channel": channel,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_push_completed(
        self,
        user_id: int,
        report_id: int,
        channel: str,
        status: str,
        conversation: dict | None = None,
    ):
        return self.publish(
            STREAM_PUSH,
            {
                "event": "push.completed",
                "user_id": user_id,
                "report_id": report_id,
                "channel": channel,
                "status": status,
                "conversation": conversation,
                "at": datetime.utcnow().isoformat(),
            },
        )

    def emit_system_error(self, agent: str, error: str):
        return self.publish(
            STREAM_SYSTEM,
            {
                "event": "system.error",
                "agent": agent,
                "error": error,
                "at": datetime.utcnow().isoformat(),
            },
        )


message_bus = MessageBus()
