"""
FastAPI entry - DailyFeed 后端 API 入口。
"""
import time
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from internal.config.settings import settings
from internal.infrastructure.database.session import get_db, init_db, is_using_sqlite
from internal.infrastructure.monitoring.logger import get_logger
from internal.orchestrator.message_bus import message_bus
from internal.orchestrator.registry import agent_registry
from api.handlers import auth as auth_handlers
from api.handlers import subscription as sub_handlers
from api.handlers import report as report_handlers
from api.handlers import user as user_handlers
from api.handlers import health as health_handlers

logger = get_logger("api")

app = FastAPI(
    title="DailyFeed API",
    version="0.2.0",
    description="DailyFeed",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Simple request logging middleware
@app.middleware("http")
async def request_logger(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
        logger.info(
            "request method=%s path=%s status=%d ms=%.1f",
            request.method, request.url.path, response.status_code,
            (time.time() - start) * 1000,
        )
        return response
    except Exception as exc:
        logger.error("request failed method=%s path=%s exc=%s",
                     request.method, request.url.path, exc)
        raise


# Include routers
app.include_router(auth_handlers.router)
app.include_router(sub_handlers.router)
app.include_router(report_handlers.router)
app.include_router(user_handlers.router)
app.include_router(health_handlers.router)


@app.on_event("startup")
def on_startup():
    """启动时：初始化数据库表。"""
    init_db()
    logger.info("startup complete. using_sqlite=%s", is_using_sqlite())


@app.get("/")
def read_root():
    return {
        "name": settings.app_name,
        "version": "0.2.0",
        "status": "ok",
        "llm": {
            "enabled": settings.llm_enabled,
            "provider": settings.llm_provider,
        },
        "database": {
            "sqlite_fallback": is_using_sqlite(),
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
