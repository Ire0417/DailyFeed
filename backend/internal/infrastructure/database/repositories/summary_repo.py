from sqlalchemy.orm import Session
from internal.infrastructure.database.models import SummaryModel, ContentModel


class SummaryRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_content_id(self, content_id: int):
        return self.session.query(SummaryModel).filter(SummaryModel.content_id == content_id).first()

    def create(self, summary: SummaryModel) -> SummaryModel:
        self.session.add(summary)
        self.session.commit()
        self.session.refresh(summary)
        return summary

    def list_by_user_for_report(self, user_id: int, report_date):
        from internal.infrastructure.database.models import ReportModel
        return self.session.query(SummaryModel).join(ContentModel).join(SubscriptionModel).filter(
            SubscriptionModel.user_id == user_id
        ).filter(
            ContentModel.published_at >= report_date
        ).all()
