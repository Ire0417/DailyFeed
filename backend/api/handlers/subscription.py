"""
Subscription handlers - 管理用户的订阅源。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from internal.infrastructure.database.session import get_db
from internal.infrastructure.database.repositories.subscription_repo import SubscriptionRepository
from internal.infrastructure.database.models import SubscriptionModel
from api.handlers.auth import get_current_user

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class CreateSubscriptionRequest(BaseModel):
    source_type: str  # rss | github | bilibili
    source_url: str
    priority: int = 3
    config: dict | None = None


class UpdateSubscriptionRequest(BaseModel):
    source_url: str | None = None
    priority: int | None = None
    is_active: bool | None = None
    config: dict | None = None


# ---------- helpers ----------
_VALID_TYPES = {"rss", "github", "bilibili"}


def _serialize(sub: SubscriptionModel) -> dict:
    return {
        "id": sub.id,
        "source_type": sub.source_type,
        "source_url": sub.source_url,
        "priority": sub.priority,
        "is_active": sub.is_active,
        "config": sub.config or {},
        "last_fetch_at": sub.last_fetch_at.isoformat() if sub.last_fetch_at else None,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
    }


@router.get("")
def list_subscriptions(user=Depends(get_current_user), db=Depends(get_db)):
    repo = SubscriptionRepository(db)
    subs = repo.list_by_user(user_id=user.id, only_active=False)
    return [_serialize(s) for s in subs]


@router.post("")
def create_subscription(
    body: CreateSubscriptionRequest,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    if body.source_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail="unsupported source_type")
    if not body.source_url or len(body.source_url) > 2048:
        raise HTTPException(status_code=400, detail="invalid source_url")

    repo = SubscriptionRepository(db)
    sub = SubscriptionModel(
        user_id=user.id,
        source_type=body.source_type,
        source_url=body.source_url,
        config=body.config or {},
        priority=body.priority,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    created = repo.create(sub)
    return _serialize(created)


@router.put("/{subscription_id}")
def update_subscription(
    subscription_id: int,
    body: UpdateSubscriptionRequest,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    repo = SubscriptionRepository(db)
    sub = repo.get_by_id(subscription_id=subscription_id, user_id=user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")

    update = {}
    if body.source_url is not None:
        update["source_url"] = body.source_url
    if body.priority is not None:
        update["priority"] = body.priority
    if body.is_active is not None:
        update["is_active"] = body.is_active
    if body.config is not None:
        update["config"] = body.config

    updated = repo.update(sub, update)
    return _serialize(updated)


@router.delete("/{subscription_id}")
def delete_subscription(
    subscription_id: int,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    repo = SubscriptionRepository(db)
    if not repo.delete(subscription_id=subscription_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"ok": True}


@router.post("/{subscription_id}/toggle")
def toggle_subscription(
    subscription_id: int,
    body: dict,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    repo = SubscriptionRepository(db)
    is_active = bool(body.get("is_active", True))
    sub = repo.toggle_active(
        subscription_id=subscription_id,
        user_id=user.id,
        is_active=is_active,
    )
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")
    return _serialize(sub)
