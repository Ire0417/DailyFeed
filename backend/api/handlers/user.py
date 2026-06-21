"""
User handlers - 更新设置（推送频道、附加收件人等）。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from internal.infrastructure.database.session import get_db
from internal.infrastructure.database.repositories.user_repo import UserRepository
from api.handlers.auth import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


class UpdateSettingsRequest(BaseModel):
    channels: list[str] | None = None  # e.g. ["email", "wechat"]
    email_recipients: list[str] | None = None
    timezone: str | None = None
    wechat_webhook: str | None = None
    dingtalk_webhook: str | None = None
    daily_hour: int | None = None
    daily_minute: int | None = None
    enable_llm: bool | None = None


@router.put("/me/settings")
def update_settings(
    body: UpdateSettingsRequest,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    user_repo = UserRepository(db)
    current = dict(user.settings or {})

    # 逐项更新（仅更新非 None 的字段）
    if body.channels is not None:
        current["channels"] = [
            c for c in body.channels if c in {"email", "wechat", "dingtalk"}
        ]
    if body.email_recipients is not None:
        current["email_recipients"] = body.email_recipients
    if body.timezone is not None:
        current["timezone"] = body.timezone
    if body.wechat_webhook is not None:
        current["wechat_webhook"] = body.wechat_webhook
    if body.dingtalk_webhook is not None:
        current["dingtalk_webhook"] = body.dingtalk_webhook
    if body.daily_hour is not None:
        current["daily_hour"] = body.daily_hour
    if body.daily_minute is not None:
        current["daily_minute"] = body.daily_minute
    if body.enable_llm is not None:
        current["enable_llm"] = body.enable_llm

    user_repo.update_settings(user_id=user.id, settings=current)
    return {"ok": True, "settings": current}
