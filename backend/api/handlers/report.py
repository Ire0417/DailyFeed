"""
Report handlers - 列表 / 详情 / 手动触发一次抓取。
"""
from fastapi import APIRouter, Depends, HTTPException

from internal.infrastructure.database.session import get_db
from internal.infrastructure.database.repositories.report_repo import ReportRepository
from internal.orchestrator.message_bus import message_bus
from api.handlers.auth import get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _serialize(report) -> dict:
    return {
        "id": report.id,
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "title": report.title,
        "stats": report.stats or {},
        "status": report.status,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "delivered_at": report.delivered_at.isoformat() if report.delivered_at else None,
    }


@router.get("")
def list_reports(user=Depends(get_current_user), db=Depends(get_db)):
    repo = ReportRepository(db)
    reports = repo.list_by_user(user_id=user.id, limit=30)
    return [_serialize(r) for r in reports]


@router.get("/{report_id}")
def get_report(report_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    repo = ReportRepository(db)
    report = repo.get_by_id(report_id=report_id, user_id=user.id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    data = _serialize(report)
    data["markdown_body"] = report.markdown_body or ""
    data["html_body"] = report.html_body or ""
    return data


@router.post("/run-now")
async def run_now(user=Depends(get_current_user), db=Depends(get_db)):
    """同步执行一次完整流水线：抓取 → 摘要 → 报告生成 → 邮件推送。"""
    from internal.orchestrator.pipeline_service import PipelineService
    service = PipelineService(db)
    result = await service.run_pipeline(user_id=user.id)
    return {
        "ok": True,
        "report_id": result["report_id"],
        "title": result["title"],
        "stats": result["stats"],
        "pushed_channels": result["pushed_channels"],
        "seconds": result["seconds"],
        "message": f"报告已生成 ({result.get('seconds', 0)}s)，推送渠道: {', '.join(result['pushed_channels']) or '无'}",
    }
