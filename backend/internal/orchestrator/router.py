from internal.orchestrator.message_bus import message_bus
from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("router")

# Event routing rules: event_name -> list of target stream(s)
ROUTING_TABLE = {
    "schedule.triggered": ["stream:fetch"],
    "fetch.completed": ["stream:summary"],
    "summary.completed": ["stream:aggregate"],
    "aggregate.completed": ["stream:push"],
}


class Router:
    """
    Message router. Inspects the payload's `event` field and
    forwards a derived message to the next stream(s) in the
    processing pipeline.
    """

    def __init__(self, bus=None):
        self.bus = bus or message_bus

    def route(self, payload: dict) -> list[str]:
        event = payload.get("event")
        if not event:
            return []
        targets = ROUTING_TABLE.get(event, [])
        results = []
        for target in targets:
            msg_id = self.bus.publish(target, payload)
            if msg_id:
                results.append(msg_id)
            logger.info(
                "routed event=%s -> stream=%s id=%s",
                event,
                target,
                msg_id,
            )
        return results

    def direct(self, stream: str, payload: dict) -> str | None:
        return self.bus.publish(stream, payload)


router = Router()
