"""SourceType —— 订阅源类型枚举。"""
from enum import Enum


class SourceType(str, Enum):
    RSS = "rss"
    GITHUB = "github"
    BILIBILI = "bilibili"

    @classmethod
    def parse(cls, value: str) -> "SourceType":
        for s in SourceType:
            if s.value == (value or "").strip().lower():
                return s
        return SourceType.RSS  # fallback
