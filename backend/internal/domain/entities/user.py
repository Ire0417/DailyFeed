"""
User DTO —— 用于 API 返回用户信息 / 认证响应。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - fallback if pydantic missing
    class BaseModel:  # type: ignore
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

        def model_dump(self):
            return dict(vars(self).items())

        def dict(self):  # legacy alias
            return self.model_dump()

    def Field(default=None, **kw):  # type: ignore
        return default


class UserResponse(BaseModel):
    id: int
    username: str
    email: str = ""
    is_active: bool = True
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None

    @classmethod
    def from_model(cls, user) -> "UserResponse":
        return cls(
            id=getattr(user, "id", 0),
            username=getattr(user, "username", ""),
            email=getattr(user, "email", ""),
            is_active=bool(getattr(user, "is_active", True)),
            created_at=_ts(getattr(user, "created_at", None)),
            last_login_at=_ts(getattr(user, "last_login_at", None)),
        )


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse | dict


def _ts(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
