"""
Content DTO —— 抓取到的原始内容条目。
"""
from __future__ import annotations

from typing import Optional

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

        def model_dump(self):
            return dict(vars(self).items())


class ContentResponse(BaseModel):
    id: int
    subscription_id: int
    title: str
    url: str = ""
    author: str = ""
    content_hash: str = ""
    published_at: Optional[str] = None
    fetched_at: Optional[str] = None
    summary: Optional["SummaryResponse"] = None

    @classmethod
    def from_model(cls, content, include_summary: bool = True) -> "ContentResponse":
        summary_obj = getattr(content, "summary", None)
        return cls(
            id=getattr(content, "id", 0),
            subscription_id=getattr(content, "subscription_id", 0),
            title=getattr(content, "title", ""),
            url=getattr(content, "url", "") or "",
            author=getattr(content, "author", "") or "",
            content_hash=getattr(content, "content_hash", "") or "",
            published_at=_ts(getattr(content, "published_at", None)),
            fetched_at=_ts(getattr(content, "fetched_at", None)),
            summary=SummaryResponse.from_model(summary_obj) if (include_summary and summary_obj is not None) else None,
        )


class SummaryResponse(BaseModel):
    id: int
    content_id: int
    summary_text: str
    generated_by: str = "extractive"
    tokens_used: int = 0
    duration_ms: int = 0
    generated_at: Optional[str] = None

    @classmethod
    def from_model(cls, summary) -> "SummaryResponse | None":
        if summary is None:
            return None
        return cls(
            id=getattr(summary, "id", 0),
            content_id=getattr(summary, "content_id", 0),
            summary_text=getattr(summary, "summary_text", ""),
            generated_by=getattr(summary, "generated_by", "extractive"),
            tokens_used=int(getattr(summary, "tokens_used", 0) or 0),
            duration_ms=int(getattr(summary, "duration_ms", 0) or 0),
            generated_at=_ts(getattr(summary, "generated_at", None)),
        )


class ReportResponse(BaseModel):
    id: int
    report_date: str = ""
    title: str = ""
    markdown_body: str = ""
    html_body: str = ""
    status: str = "draft"
    stats: dict = {}
    delivered_at: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_model(cls, report, include_body: bool = True) -> "ReportResponse":
        return cls(
            id=getattr(report, "id", 0),
            report_date=str(getattr(report, "report_date", "")),
            title=getattr(report, "title", "") or "",
            markdown_body=getattr(report, "markdown_body", "") if include_body else "",
            html_body=getattr(report, "html_body", "") if include_body else "",
            status=getattr(report, "status", "draft") or "draft",
            stats=getattr(report, "stats", {}) or {},
            delivered_at=_ts(getattr(report, "delivered_at", None)),
            created_at=_ts(getattr(report, "created_at", None)),
        )


def _ts(value) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)
