import time
from functools import wraps
from internal.config.settings import settings
from internal.infrastructure.monitoring.logger import get_logger
from internal.orchestrator.message_bus import message_bus

logger = get_logger("supervisor")


class Supervisor:
    """
    Global agent supervisor. Tracks agent health, enforces task
    timeouts, keeps failure counts, and applies simple circuit breakers,
    and records system errors to the system stream.
    """

    def __init__(self, timeout_seconds: int | None = None, max_retries: int | None = None):
        self.timeout = timeout_seconds or settings.agent_timeout_seconds
        self.max_retries = max_retries or settings.agent_max_retries
        self._failures: dict[str, int] = {}
        self._open_circuit: dict[str, bool] = {}
        self._start_times: dict[str, float] = {}

    # ---------- Timeout tracking ----------
    def start(self, task_id: str):
        self._start_times[task_id] = time.time()

    def elapsed(self, task_id: str) -> float:
        start = self._start_times.get(task_id)
        if start is None:
            return 0.0
        return time.time() - start

    def timed_out(self, task_id: str) -> bool:
        return self.elapsed(task_id) > self.timeout

    def done(self, task_id: str):
        self._start_times.pop(task_id, None)

    # ---------- Failure tracking ----------
    def record_failure(self, agent: str, error: str | Exception, detail: str = ""):
        self._failures[agent] = self._failures.get(agent, 0) + 1
        message = f"{agent}: {error} {detail}".strip()
        message_bus.emit_system_error(agent=agent, error=message)
        logger.error("supervisor: %s", message)

    def record_success(self, agent: str):
        self._failures[agent] = 0
        self._open_circuit[agent] = False

    def is_circuit_open(self, agent: str) -> bool:
        return self._open_circuit.get(agent, False)

    def failures(self, agent: str) -> int:
        return self._failures.get(agent, 0)

    def open_circuit(self, agent: str):
        self._open_circuit[agent] = True
        logger.warning("circuit open for %s", agent)

    def close_circuit(self, agent: str):
        self._open_circuit[agent] = False

    # ---------- Decorators ----------
    def retry(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                        last_exc = exc
                        delay = min(2 ** attempt, 30)
                        logger.warning(
                            "%s attempt %d failed: %s — sleep %ds",
                            func.__name__, attempt, exc, delay)
                        time.sleep(delay)
            if last_exc is not None:
                raise last_exc
        return wrapper

    def guarded(self, agent: str):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if self.is_circuit_open(agent):
                    logger.warning("circuit open; skipping %s", func.__name__)
                    return None
                try:
                    result = func(*args, **kwargs)
                    self.record_success(agent)
                    return result
                except Exception as exc:
                    self.record_failure(agent, exc)
                    if self.failures(agent) >= self.max_retries:
                        self.open_circuit(agent)
                    return None
            return wrapper
        return decorator

    # ---------- Status ----------
    def status(self) -> dict:
        return {
            "timeout_seconds": self.timeout,
            "max_retries": self.max_retries,
            "failures": dict(self._failures),
            "circuits": dict(self._open_circuit),
            "circuits_open": sum(1 for v in self._open_circuit.values() if v),
        }


supervisor = Supervisor()
