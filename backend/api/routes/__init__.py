from fastapi import FastAPI
from ..handlers import auth, subscription, report, user, health


def register_routes(app: FastAPI) -> None:
    app.include_router(auth.router)
    app.include_router(subscription.router)
    app.include_router(report.router)
    app.include_router(user.router)
    app.include_router(health.router)
