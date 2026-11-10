from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

import app.models  # noqa: F401  (registers all tables)
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.modules.claims.router import router as claims_router
from app.modules.found_items import service as found_items_service
from app.modules.found_items.router import router as found_items_router
from app.modules.identity.router import router as identity_router
from app.modules.locker.router import router as locker_router
from app.modules.lost_reports.router import router as lost_reports_router
from app.modules.matching.router import router as matching_router
from app.shared.audit_router import router as audit_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await found_items_service.requeue_pending()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=settings.session_max_age_s,
        same_site="lax",
        https_only=False,  # demo runs on plain HTTP (D11)
    )
    register_error_handlers(app)
    app.include_router(identity_router)
    app.include_router(locker_router)
    app.include_router(found_items_router)
    app.include_router(lost_reports_router)
    app.include_router(matching_router)
    app.include_router(claims_router)
    app.include_router(audit_router)

    @app.get("/api/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
