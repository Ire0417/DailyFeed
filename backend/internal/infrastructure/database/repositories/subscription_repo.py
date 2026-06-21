from datetime import datetime
from sqlalchemy.orm import Session
from internal.infrastructure.database.models import SubscriptionModel


class SubscriptionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_user(self, user_id: int, only_active: bool = True):
        query = self.session.query(SubscriptionModel).filter(SubscriptionModel.user_id == user_id)
        if only_active:
            query = query.filter(SubscriptionModel.is_active == True)
        return query.order_by(SubscriptionModel.priority.desc(), SubscriptionModel.created_at.desc()).all()

    def get_by_id(self, subscription_id: int, user_id: int | None = None):
        query = self.session.query(SubscriptionModel).filter(SubscriptionModel.id == subscription_id)
        if user_id is not None:
            query = query.filter(SubscriptionModel.user_id == user_id)
        return query.first()

    def create(self, subscription: SubscriptionModel) -> SubscriptionModel:
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def update(self, subscription: SubscriptionModel, data: dict) -> SubscriptionModel:
        for key, value in data.items():
            if hasattr(subscription, key):
                setattr(subscription, key, value)
        subscription.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def delete(self, subscription_id: int, user_id: int | None = None):
        sub = self.get_by_id(subscription_id, user_id)
        if sub:
            self.session.delete(sub)
            self.session.commit()
            return True
        return False

    def toggle_active(self, subscription_id: int, user_id: int, is_active: bool):
        sub = self.get_by_id(subscription_id, user_id)
        if sub:
            sub.is_active = is_active
            sub.updated_at = datetime.utcnow()
            self.session.commit()
            return sub
        return None

    def update_last_fetch(self, subscription_id: int):
        sub = self.session.query(SubscriptionModel).filter(SubscriptionModel.id == subscription_id).first()
        if sub:
            sub.last_fetch_at = datetime.utcnow()
            self.session.commit()
