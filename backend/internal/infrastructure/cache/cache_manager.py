import json
from internal.infrastructure.cache.redis_client import redis_client


class CacheManager:
    """
    Simple cache wrapper with key prefixing and JSON (de)serialization.
    Falls back to the in-memory store in RedisClient if Redis is unavailable.
    """

    def __init__(self, key_prefix: str = "dailyfeed"):
        self.redis = redis_client
        self.key_prefix = key_prefix

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}:{key}"

    def get(self, key: str):
        raw = self.redis.get(self._make_key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw

    def set(self, key: str, value, ttl_seconds: int = 3600):
        if not isinstance(value, (str, bytes)):
            try:
                value = json.dumps(value, ensure_ascii=False)
            except Exception:
                value = str(value)
        self.redis.set(self._make_key(key), value, ttl_seconds)

    def delete(self, key: str):
        self.redis.delete(self._make_key(key))

    def exists(self, key: str) -> bool:
        return self.redis.get(self._make_key(key)) is not None


cache_manager = CacheManager()
