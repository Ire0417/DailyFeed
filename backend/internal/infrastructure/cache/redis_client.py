import json
from internal.config.settings import settings

try:
    import redis as _redis
    _HAS_REDIS = True
except Exception:
    _HAS_REDIS = False


class RedisClient:
    """
    Redis client wrapper. Falls back to an in-memory dict if Redis
    is not available (so the system can still run in development).
    """

    def __init__(self):
        self._client = None
        self._fallback: dict[str, tuple[bytes, float]] = {}
        self._connect()

    def _connect(self):
        if not _HAS_REDIS:
            self._client = None
            return
        try:
            self._client = _redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password,
                db=settings.redis_db,
                decode_responses=False,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            self._client.ping()
        except Exception:
            self._client = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    def get(self, key: str):
        if self._client:
            try:
                return self._client.get(key)
            except Exception:
                pass
        entry = self._fallback.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        import time
        if expire_at and expire_at < time.time():
            del self._fallback[key]
            return None
        return value

    def set(self, key: str, value, ttl_seconds: int = 3600):
        if not isinstance(value, (bytes, str, int, float)):
            try:
                value = json.dumps(value)
            except Exception:
                value = str(value)
        if self._client:
            try:
                self._client.set(key, value, ex=ttl_seconds)
                return
            except Exception:
                pass
        import time
        self._fallback[key] = (
            value.encode("utf-8") if isinstance(value, str) else value,
            time.time() + ttl_seconds,
        )

    def delete(self, key: str):
        if self._client:
            try:
                self._client.delete(key)
                return
            except Exception:
                pass
        self._fallback.pop(key, None)

    # ---------- Redis Stream helpers ----------
    def xadd(self, stream: str, fields: dict) -> str | None:
        if self._client:
            try:
                return self._client.xadd(stream, fields)
            except Exception:
                pass
        import time
        import uuid
        msg_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}"
        self._fallback.setdefault(f"stream:{stream}", []).append((msg_id, fields))
        return msg_id

    def xread(self, streams: dict[str, str], count: int = 10, block_ms: int = 1000) -> dict[str, list]:
        if self._client:
            try:
                result = self._client.xread(streams, count=count, block=block_ms)
                out = {}
                for entry in result:
                    stream_name = entry[0]
                    messages = []
                    for msg in entry[1]:
                        msg_id = msg[0]
                        fields = msg[1]
                        # Decode bytes to strings
                        decoded = {}
                        for k, v in fields.items():
                            if isinstance(k, bytes):
                                k = k.decode("utf-8")
                            if isinstance(v, bytes):
                                v = v.decode("utf-8")
                            decoded[k] = v
                        messages.append({"id": msg_id, "fields": decoded})
                    out[stream_name] = messages
                return out
            except Exception:
                pass
        out = {}
        for stream, last_id in streams.items():
            buf = self._fallback.get(f"stream:{stream}", [])
            messages = []
            for msg_id, fields in buf:
                if last_id and msg_id <= last_id:
                    continue
                messages.append({"id": msg_id, "fields": fields})
            if messages:
                out[stream] = messages[:count]
        return out

    def close(self):
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass


redis_client = RedisClient()
