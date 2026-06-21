from pydantic import BaseModel
from typing import Any


class SubscriptionIn(BaseModel):
    source_type: str
    source_config: dict[str, Any] | None = None
    priority: str = "normal"


class SubscriptionOut(BaseModel):
    id: int | None = None
    source_type: str = ""
    priority: str = "normal"
    is_active: bool = True
