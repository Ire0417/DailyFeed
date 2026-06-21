from __future__ import annotations

from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def new_context(
    user_id: int,
    *,
    plan: str = "",
    summary: str = "",
    next_agent: str = "",
    memo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "user_id": int(user_id or 0),
        "plan": plan or "",
        "summary": summary or "",
        "next_agent": next_agent or "",
        "memo": dict(memo or {}),
        "history": [],
    }


def ensure_context(payload: dict[str, Any], *, default_next_agent: str = "") -> dict[str, Any]:
    raw = payload.get("conversation")
    user_id = int(payload.get("user_id") or 0)
    if isinstance(raw, dict):
        raw["user_id"] = int(raw.get("user_id") or user_id)
        raw["plan"] = str(raw.get("plan") or "")
        raw["summary"] = str(raw.get("summary") or "")
        raw["next_agent"] = str(raw.get("next_agent") or default_next_agent or "")
        raw["memo"] = dict(raw.get("memo") or {})
        raw["history"] = list(raw.get("history") or [])
        context = raw
    else:
        context = new_context(
            user_id=user_id,
            plan=f"run pipeline for user {user_id}",
            next_agent=default_next_agent,
            memo={
                "content_ids": list(payload.get("content_ids") or []),
                "count": int(payload.get("count") or 0),
            },
        )

    payload["conversation"] = context
    payload["user_id"] = context["user_id"]
    return context


def append_history(
    context: dict[str, Any],
    *,
    agent: str,
    message: str,
    next_agent: str | None = None,
    plan: str | None = None,
    summary: str | None = None,
    memo_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history = context.setdefault("history", [])
    history.append(
        {
            "agent": agent,
            "message": message,
            "at": _now_iso(),
        }
    )
    if len(history) > 40:
        context["history"] = history[-40:]

    if next_agent is not None:
        context["next_agent"] = next_agent
    if plan is not None:
        context["plan"] = plan
    if summary is not None:
        context["summary"] = summary
    if memo_updates:
        memo = context.setdefault("memo", {})
        memo.update(memo_updates)
    return context
