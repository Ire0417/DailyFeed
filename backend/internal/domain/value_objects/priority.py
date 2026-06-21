"""Priority —— 订阅优先级（1 最高 · 5 最低，默认 3）。"""
from enum import IntEnum


class Priority(IntEnum):
    HIGH = 1
    HIGH_MID = 2
    NORMAL = 3
    MID = 4
    LOW = 5

    @classmethod
    def parse(cls, value, default: "Priority" = None) -> "Priority":
        try:
            try:
                # Match by IntEnum value
                v = int(value)
                for p in cls:
                    if p.value == v:
                        return p
            except Exception:
                pass
            name = str(value).strip().lower()
            for p in cls:
                    if p.name.lower() == name:
                        return p
        except Exception:
            pass
        return default or cls.NORMAL
