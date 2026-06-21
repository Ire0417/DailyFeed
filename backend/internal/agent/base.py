import asyncio
import signal
import time
from internal.config.settings import settings
from internal.infrastructure.monitoring.logger import get_logger, log_extra
from internal.orchestrator.message_bus import message_bus, STREAM_SCHEDULE, STREAM_FETCH, STREAM_SUMMARY, STREAM_AGGREGATE, STREAM_PUSH
from internal.orchestrator.registry import agent_registry
from internal.orchestrator.supervisor import supervisor


class BaseAgent:
    """
    Base class for all DailyFeed agents. Handles lifecycle, heartbeats,
    message consumption, and graceful shutdown.

    Subclasses override:
        - streams: streams to consume
        - process(payload): handle a single message payload
    """

    name = "base"
    poll_interval_seconds = 5
    heartbeat_interval_seconds = 30

    def __init__(self):
        self.logger = get_logger(self.name)
        self._running = False
        self._last_heartbeat = 0.0
        self._streams: list[str] = []
        self._last_ids: dict[str, str] = {}

    # ---------- Lifecycle ----------
    def start(self):
        agent_registry.register(self.name, self)
        self._running = True
        self.logger.info("agent started")
        try:
            asyncio.run(self._loop())
        except KeyboardInterrupt:
            self.logger.info("received interrupt, shutting down")
        finally:
            self.stop()

    def stop(self):
        self._running = False
        agent_registry.unregister(self.name)
        self.logger.info("agent stopped")

    # ---------- Main loop ----------
    async def _loop(self):
        last_heartbeat = 0.0
        while self._running:
            now = time.time()

            # heartbeat
            if now - last_heartbeat >= self.heartbeat_interval_seconds:
                agent_registry.heartbeat(self.name, status="running")
                last_heartbeat = now

            # consume messages from subscribed streams
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

    def _handle_message(self, stream: str, message: dict):
        payload = message.get("payload", {})
        task_id = f"{self.name}:{message.get('id')}:{payload.get('event')}"
        supervisor.start(task_id)
        try:
            result = self.process(stream, payload)
            supervisor.record_success(self.name)
            return result
        except Exception as exc:
            supervisor.record_failure(self.name, exc)
            self.logger.error(
                "process failed: %s", exc,
                extra=log_extra(agent=self.name, user_id=payload.get("user_id")),
            )
            return None
        finally:
            if not supervisor.timed_out(task_id):
                supervisor.done(task_id)

    # ---------- To override ----------
    def process(self, stream: str, payload: dict):
        return None
