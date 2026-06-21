"""
Subscription DTO —— 订阅资源列表 / 创建 / 更新。
"""
from __future__ import annotations

from typing import Optional, Dict, Any

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

        def model_dump(self):
            return dict(vars(self).items())


class SubscriptionResponse(BaseModel):
    id: int
    source_type: str
    source_url: str
    label: str = ""
    priority: int = 3
    is_active: bool = True
    last_fetch_at: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_model(cls, sub) -> "SubscriptionResponse":
        return cls(
            id=getattr(sub, "id", 0),
            source_type=getattr(sub, "source_type", ""),
            source_url=getattr(sub, "source_url", ""),
            label=getattr(sub, "config", {}).get("label", "")
                  if isinstance(getattr(sub, "config", None), dict)
                  else getattr(sub, "label", ""),
            priority=int(getattr(sub, "priority", 3)),
            is_active=bool(getattr(sub, "is_active", True)),
            last_fetch_at=_ts(getattr(sub, "last_fetch_at", None)),
            created_at=_ts(getattr(sub, "created_at", None)),
        )


class CreateSubscriptionRequest(BaseModel):
    source_type: str
    source_url: str
    label: str = ""
    priority: int = 3
    config: Dict[str, Any] = {}


class UpdateSubscriptionRequest(BaseModel):
    label: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    source_url: Optional[str] = None


def _ts(value) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)
