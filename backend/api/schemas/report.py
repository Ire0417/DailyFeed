from pydantic import BaseModel
from datetime import datetime


class ReportOut(BaseModel):
    id: int | None = None
    title: str = ""
    status: str = "draft"
    report_date: datetime | None = None
    markdown_body: str = ""
