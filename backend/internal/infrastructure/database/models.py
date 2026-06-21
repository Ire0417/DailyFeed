from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, JSON, SmallInteger, Date
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    settings = Column(JSON, default=lambda: {})
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subscriptions = relationship("SubscriptionModel", back_populates="user", cascade="all, delete-orphan")
    reports = relationship("ReportModel", back_populates="user", cascade="all, delete-orphan")


class SubscriptionModel(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    source_type = Column(String(32), index=True, nullable=False)
    source_url = Column(String(1024), nullable=False)
    config = Column(JSON, default=lambda: {})
    priority = Column(SmallInteger, default=3, index=True)
    is_active = Column(Boolean, default=True, index=True)
    last_fetch_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("UserModel", back_populates="subscriptions")
    contents = relationship("ContentModel", back_populates="subscription", cascade="all, delete-orphan")


class ContentModel(Base):
    __tablename__ = "contents"

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), index=True, nullable=False)
    title = Column(String(512), nullable=False)
    author = Column(String(128))
    raw_content = Column(Text)
    url = Column(String(2048))
    content_hash = Column(String(128), index=True)
    published_at = Column(DateTime, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    subscription = relationship("SubscriptionModel", back_populates="contents")
    summary = relationship("SummaryModel", back_populates="content", uselist=False, cascade="all, delete-orphan")


class SummaryModel(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True)
    content_id = Column(Integer, ForeignKey("contents.id"), index=True, nullable=False)
    summary_text = Column(Text, nullable=False)
    generated_by = Column(String(32), default="llm")
    tokens_used = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    generated_at = Column(DateTime, default=datetime.utcnow)

    content = relationship("ContentModel", back_populates="summary")


class ReportModel(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    report_date = Column(Date, index=True, nullable=False)
    title = Column(String(256))
    markdown_body = Column(Text)
    html_body = Column(Text)
    stats = Column(JSON, default=lambda: {})
    status = Column(String(32), default="draft", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)

    user = relationship("UserModel", back_populates="reports")
    push_logs = relationship("PushLogModel", back_populates="report", cascade="all, delete-orphan")


class PushLogModel(Base):
    __tablename__ = "push_logs"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id"), index=True, nullable=False)
    channel = Column(String(32), index=True)
    status = Column(String(32))
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    report = relationship("ReportModel", back_populates="push_logs")
