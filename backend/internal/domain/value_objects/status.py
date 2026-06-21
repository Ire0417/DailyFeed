"""Status —— 订阅/报告/推送状态枚举。"""
from enum import Enum


class Status(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ACTIVE = "active"
    INACTIVE = "inactive"

    @classmethod
    def parse(cls, value: str, default: "Status" = None) -> "Status":
        for s in cls:
            if s.value == (value or "").strip().lower():
                return s
        return default or cls.PENDING
