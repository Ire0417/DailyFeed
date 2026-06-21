import time
import asyncio
from datetime import datetime
from .base import BaseAgent
from internal.config.settings import settings
from internal.orchestrator.message_bus import message_bus, STREAM_SCHEDULE
from internal.orchestrator.registry import agent_registry
from internal.infrastructure.database.session import get_session
from internal.infrastructure.database.models import UserModel
from internal.infrastructure.monitoring import metrics


class SchedulerAgent(BaseAgent):
    """
    Scheduler agent. Periodically checks schedule configuration and, at the
    configured hour/minute, emits `schedule.triggered` events for each
    active user.

    Supports manual triggers by emitting events with event="schedule.manual".
    """

    name = "scheduler"
    poll_interval_seconds = 60

    def __init__(self):
        super().__init__()
        self._streams = [STREAM_SCHEDULE]
        self._last_run_date = ""

    def process(self, stream: str, payload: dict):
        event = payload.get("event")
        if event == "schedule.manual":
            user_id = payload.get("user_id", 0)
            self._trigger_for_user(user_id)
            return {"ok": True, "user_id": user_id}
        return None

    # ---------- Internal scheduling ----------
    async def _loop(self):
        last_heartbeat = 0.0
        while self._running:
            now = time.time()
            if now - last_heartbeat >= self.heartbeat_interval_seconds:
                agent_registry.heartbeat(self.name, status="running")
                last_heartbeat = now

            try:
                self._check_schedule()
            except Exception as exc:
                self.logger.error("schedule check failed: %s", exc)

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

    def _check_schedule(self):
        now = datetime.utcnow()
        target_today = now.replace(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            second=0,
            microsecond=0,
        )
        key = target_today.strftime("%Y-%m-%d")
        if now >= target_today and self._last_run_date != key:
            self._trigger_all_users()
            self._last_run_date = key

    def _trigger_all_users(self):
        self.logger.info("scheduler: triggering daily run")
        count = 0
        with get_session() as session:
            users = session.query(UserModel).filter(UserModel.is_active == True).limit(1000).all()
            for user in users:
                message_bus.emit_schedule_triggered(user_id=user.id)
                count += 1
        metrics.counter("scheduler.triggers_emitted", count)
        metrics.gauge("scheduler.active_users", count)
        self.logger.info("scheduler: emitted %d triggers", count)

    def _trigger_for_user(self, user_id: int):
        if user_id == 0:
            self._trigger_all_users()
            return
        message_bus.emit_schedule_triggered(user_id=user_id)
        metrics.counter("scheduler.manual_triggers", 1)
        self.logger.info("scheduler: manual trigger for user_id=%d", user_id)
