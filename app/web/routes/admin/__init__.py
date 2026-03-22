from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.services.admin import latest_closed_month_with_transactions

from .analysis import router as analysis_router
from .auth import router as auth_router
from .categories import router as categories_router
from .dashboard import admin_create_credit_card, admin_home, admin_upload_credit_card_bill
from .helpers import parse_optional_date, render_admin, templates
from .invoices import router as invoices_router
from .reapply import router as reapply_router
from .rules import router as rules_router
from .transactions import router as transactions_router

router = APIRouter(prefix="/admin", include_in_schema=False)
router.add_api_route("", admin_home, methods=["GET"], response_class=HTMLResponse)
router.add_api_route("/", admin_home, methods=["GET"], response_class=HTMLResponse)
router.add_api_route("/credit-cards", admin_create_credit_card, methods=["POST"])
router.add_api_route("/credit-card-bills/upload", admin_upload_credit_card_bill, methods=["POST"])
router.include_router(auth_router)
router.include_router(analysis_router)
router.include_router(invoices_router)
router.include_router(transactions_router)
router.include_router(rules_router)
router.include_router(categories_router)
router.include_router(reapply_router)

__all__ = [
    "router",
    "render_admin",
    "parse_optional_date",
    "templates",
    "latest_closed_month_with_transactions",
]
