import time
from datetime import datetime
from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("agent_registry")


class AgentRegistry:
    """
    Service registry for agents.

    Each agent registers itself with `register(name, instance)`.
    The registry tracks liveness by recording periodic heartbeats.
    """

    def __init__(self):
        self._agents: dict[str, dict] = {}

    def register(self, name: str, instance):
        self._agents[name] = {
            "instance": instance,
            "registered_at": datetime.utcnow(),
            "last_heartbeat": time.time(),
            "status": "idle",
        }
        logger.info("agent registered: %s", name)

    def unregister(self, name: str):
        self._agents.pop(name, None)
        logger.info("agent unregistered: %s", name)

    def heartbeat(self, name: str, status: str = "running"):
        entry = self._agents.get(name)
        if entry:
            entry["last_heartbeat"] = time.time()
            entry["status"] = status

    def get(self, name: str):
        entry = self._agents.get(name)
        return entry["instance"] if entry else None

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def status(self, name: str):
        entry = self._agents.get(name)
        if not entry:
            return None
        return {
            "status": entry["status"],
            "registered_at": entry["registered_at"].isoformat(),
            "last_heartbeat": entry["last_heartbeat"],
            "seconds_since_heartbeat": int(time.time() - entry["last_heartbeat"]),
        }

    def health(self) -> dict[str, dict]:
        return {name: self.status(name) for name in self._agents}

    def dead_agents(self, idle_timeout: int = 60) -> list[str]:
        now = time.time()
        return [
            name
            for name, entry in self._agents.items()
            if now - entry["last_heartbeat"] > idle_timeout
        ]
agent_registry = AgentRegistry()
