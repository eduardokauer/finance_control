from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.analysis import router as analysis_router
from app.api.routes.health import router as health_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.transactions import router as transactions_router
from app.core.config import settings
from app.core.responses import UTF8JSONResponse
from app.web.routes.admin import router as admin_router

app = FastAPI(title=settings.app_name, default_response_class=UTF8JSONResponse)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.admin_ui_session_secret,
    session_cookie="finance_control_admin_session",
    same_site="lax",
    https_only=settings.environment == "prod",
)
app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(transactions_router)
app.include_router(analysis_router)
app.include_router(admin_router)
