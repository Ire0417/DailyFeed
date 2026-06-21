from datetime import datetime
from sqlalchemy.orm import Session
from internal.infrastructure.database.models import ContentModel


class ContentRepository:
    def __init__(self, session: Session):
        self.session = session

    def exists_by_hash(self, content_hash: str) -> bool:
        return self.session.query(ContentModel).filter(ContentModel.content_hash == content_hash).first() is not None

    def list_by_subscription(self, subscription_id: int, since: datetime | None = None, limit: int = 100):
        query = self.session.query(ContentModel).filter(ContentModel.subscription_id == subscription_id)
        if since:
            query = query.filter(ContentModel.published_at >= since)
        return query.order_by(ContentModel.published_at.desc()).limit(limit).all()

    def create(self, content: ContentModel) -> ContentModel:
        self.session.add(content)
        self.session.commit()
        self.session.refresh(content)
        return content

    def bulk_create(self, contents: list[ContentModel]) -> int:
        if not contents:
            return 0
        self.session.add_all(contents)
        self.session.commit()
        return len(contents)

    def get_pending_summary(self, since: datetime, limit: int = 100):
        from internal.infrastructure.database.models import SummaryModel
        return (
            self.session.query(ContentModel)
            .filter(ContentModel.id.not_in(self.session.query(SummaryModel.content_id)))
            .filter(ContentModel.fetched_at >= since)
            .order_by(ContentModel.fetched_at.desc())
            .limit(limit)
            .all()
        )
