from datetime import datetime
from sqlalchemy.orm import Session
from internal.infrastructure.database.models import UserModel


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, user_id: int):
        return self.session.query(UserModel).filter(UserModel.id == user_id).first()

    def get_by_email(self, email: str):
        return self.session.query(UserModel).filter(UserModel.email == email.lower()).first()

    def get_by_username(self, username: str):
        return self.session.query(UserModel).filter(UserModel.username == username).first()

    def create(self, user: UserModel) -> UserModel:
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def update_last_login(self, user_id: int):
        user = self.session.query(UserModel).filter(UserModel.id == user_id).first()
        if user:
            user.last_login_at = datetime.utcnow()
            self.session.commit()

    def update_settings(self, user_id: int, settings: dict):
        user = self.session.query(UserModel).filter(UserModel.id == user_id).first()
        if user:
            user.settings = settings
            user.updated_at = datetime.utcnow()
            self.session.commit()
