import asyncio
import signal
import time
from internal.config.settings import settings
from internal.infrastructure.monitoring.logger import get_logger, log_extra
from internal.orchestrator.message_bus import message_bus, STREAM_SCHEDULE, STREAM_FETCH, STREAM_SUMMARY, STREAM_AGGREGATE, STREAM_PUSH
from internal.orchestrator.supervisor import supervisor
from internal.orchestrator.conversation_context import ensure_context
from internal.memory import get_memory_router, AccessLevel

from internal.orchestrator.registry import agent_registry


class BaseAgent:
    """
    所有agent统一交互协议
    方便orchestrator统一调度
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
        self.memory = get_memory_router()
        self._declare_memory_acl()

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
        context = ensure_context(payload)
        user_id = int(context.get("user_id") or payload.get("user_id") or 0)
        task_id = f"{self.name}:{message.get('id')}:{payload.get('event')}"
        supervisor.start(task_id)
        try:
            if user_id > 0:
                session_id = context.setdefault("memo", {}).get("session_id")
                session_id = self.memory.open_session(
                    user_id=user_id,
                    session_id=session_id,
                    agent_name=self.name,
                )
                context["memo"]["session_id"] = session_id
                self.memory.add_agent_message(
                    session_id,
                    self.name,
                    f"received {payload.get('event')}",
                    agent_name=self.name,
                )
                context["memo"]["task_id"] = self.memory.start_task(
                    owner=self.name,
                    user_id=user_id,
                    agent_name=self.name,
                )
            result = self.process(stream, payload)
            if user_id > 0:
                self.memory.remember_long_term(
                    kind=self._memory_kind_for_result(),
                    content=f"{self.name} handled event={payload.get('event')} result={bool(result)}",
                    user_id=user_id,
                    tags=[self.name, str(payload.get("event") or "")],
                    agent_name=self.name,
                )
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

    def _memory_kind_for_result(self):
        from internal.memory import MemoryKind
        return MemoryKind.LTM

    def _declare_memory_acl(self):
        self.memory.declare_agent(
            self.name,
            global_shared=AccessLevel.READ_WRITE,
            session_isolated=AccessLevel.READ_WRITE,
            task_specific=AccessLevel.READ_WRITE,
        )
