from datetime import datetime, date
from sqlalchemy.orm import Session
from internal.infrastructure.database.models import ReportModel, PushLogModel


class ReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_user(self, user_id: int, limit: int = 30):
        return (
            self.session.query(ReportModel)
            .filter(ReportModel.user_id == user_id)
            .order_by(ReportModel.report_date.desc())
            .limit(limit)
            .all()
        )

    def get_by_id(self, report_id: int, user_id: int | None = None):
        query = self.session.query(ReportModel).filter(ReportModel.id == report_id)
        if user_id is not None:
            query = query.filter(ReportModel.user_id == user_id)
        return query.first()

    def get_by_date(self, user_id: int, report_date: date):
        return (
            self.session.query(ReportModel)
            .filter(ReportModel.user_id == user_id, ReportModel.report_date == report_date)
            .first()
        )

    def create(self, report: ReportModel) -> ReportModel:
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def update_status(self, report_id: int, status: str):
        report = self.session.query(ReportModel).filter(ReportModel.id == report_id).first()
        if report:
            report.status = status
            if status == "delivered":
                report.delivered_at = datetime.utcnow()
            self.session.commit()

    def add_push_log(self, report_id: int, channel: str, status: str, error_message: str | None = None):
        log = PushLogModel(report_id=report_id, channel=channel, status=status, error_message=error_message)
        self.session.add(log)
        self.session.commit()
