import functools
import asyncio
from typing import Callable


def retry(times: int = 3, delay: float = 1.0, exceptions: tuple = (Exception,)):
    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(times):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    await asyncio.sleep(delay * (attempt + 1))
            if last_exception:
                raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            import time
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    time.sleep(delay * (attempt + 1))
            if last_exception:
                raise last_exception

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
