"""
Health handler - 健康检查 & agent/系统状态。
"""
from fastapi import APIRouter, Depends
from internal.config.settings import settings
from internal.orchestrator.registry import agent_registry
from internal.orchestrator.supervisor import supervisor
from internal.infrastructure.monitoring import metrics
from api.handlers.auth import get_current_user

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.env,
    }


@router.get("/status")
def status(user=Depends(get_current_user)):
    return {
        "registry": {
            "agents": agent_registry.list(),
            "health": agent_registry.health(),
        },
        "supervisor": supervisor.status(),
    }


@router.get("/metrics")
def metrics_endpoint(user=Depends(get_current_user)):
    """返回累加计数器与瞬时指标。"""
    return metrics.snapshot()

