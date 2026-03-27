from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import latest_analysis_run_for_period, renderable_analysis_html, resolve_analysis_period
from app.services.analysis import build_analysis_snapshot, parse_analysis_payload

from .helpers import render_admin

router = APIRouter()


def _analysis_page_context(
    db: Session,
    *,
    base_path: str,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
) -> dict:
    latest_closed_start, latest_closed_end = resolve_analysis_period(
        db,
        month=None,
        period_start=None,
        period_end=None,
    )
    selected_mode = selection_mode or ("custom" if period_start and period_end else ("month" if month else "closed"))
    month_value = month or f"{latest_closed_start.year:04d}-{latest_closed_start.month:02d}"
    month_preview_start, month_preview_end = resolve_analysis_period(
        db,
        month=month_value,
        period_start=None,
        period_end=None,
    )

    if selected_mode == "month":
        resolved_start, resolved_end = month_preview_start, month_preview_end
    elif selected_mode == "custom" and period_start and period_end:
        resolved_start, resolved_end = resolve_analysis_period(
            db,
            month=None,
            period_start=period_start,
            period_end=period_end,
        )
    else:
        resolved_start, resolved_end = latest_closed_start, latest_closed_end

    analysis_run = latest_analysis_run_for_period(db, period_start=resolved_start, period_end=resolved_end)
    live_snapshot = build_analysis_snapshot(db, period_start=resolved_start, period_end=resolved_end)
    payload_snapshot = parse_analysis_payload(analysis_run.payload) if analysis_run else None
    if payload_snapshot and "conciliation_signals" not in payload_snapshot:
        payload_snapshot["conciliation_signals"] = live_snapshot["conciliation_signals"]
    if payload_snapshot and "conciliated_month" not in payload_snapshot:
        payload_snapshot["conciliated_month"] = live_snapshot["conciliated_month"]
    if payload_snapshot and "primary_summary" not in payload_snapshot:
        payload_snapshot["primary_summary"] = live_snapshot["primary_summary"]
    if payload_snapshot:
        payload_snapshot["home_cards"] = live_snapshot["home_cards"]
        payload_snapshot["category_breakdown"] = live_snapshot["category_breakdown"]
        payload_snapshot["category_history"] = live_snapshot["category_history"]
        payload_snapshot["categories"] = live_snapshot["categories"]
        payload_snapshot["top_expense_categories"] = live_snapshot["top_expense_categories"]
        payload_snapshot["alerts"] = live_snapshot["alerts"]
        payload_snapshot["actions"] = live_snapshot["actions"]
        payload_snapshot.setdefault("charts", {})
        payload_snapshot["charts"]["categories"] = live_snapshot["charts"]["categories"]
    analysis_data = payload_snapshot or live_snapshot
    summary_categories = [
        item for item in analysis_data.get("top_expense_categories", []) if not item.get("is_technical")
    ][:4]
    return {
        "selection_mode": selected_mode,
        "period_start": resolved_start,
        "period_end": resolved_end,
        "month_value": month_value,
        "latest_closed_start": latest_closed_start,
        "latest_closed_end": latest_closed_end,
        "month_preview_start": month_preview_start,
        "month_preview_end": month_preview_end,
        "summary": analysis_data.get("primary_summary", analysis_data["summary"]),
        "analysis_run": analysis_run,
        "analysis_data": analysis_data,
        "analysis_html_fragment": renderable_analysis_html(analysis_run.html_output) if analysis_run else None,
        "llm_html_available": False,
        "summary_categories": summary_categories,
        "priority_alerts": analysis_data.get("alerts", [])[:3],
        "priority_actions": analysis_data.get("actions", [])[:2],
        "analysis_urls": {
            "summary": f"/admin?period_start={resolved_start.isoformat()}&period_end={resolved_end.isoformat()}",
            "detail": f"/admin/analysis?period_start={resolved_start.isoformat()}&period_end={resolved_end.isoformat()}",
            "conference": f"/admin/conference?period_start={resolved_start.isoformat()}&period_end={resolved_end.isoformat()}",
            "operations": "/admin/operations",
            "return_to": f"{base_path}?period_start={resolved_start.isoformat()}&period_end={resolved_end.isoformat()}",
        },
    }


def admin_summary_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/summary.html",
        _analysis_page_context(
            db,
            base_path="/admin",
            selection_mode=selection_mode,
            month=month,
            period_start=period_start,
            period_end=period_end,
        ),
    )


@router.get("/summary", response_class=HTMLResponse)
def admin_summary_alias_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return admin_summary_page(
        request=request,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
        db=db,
        _=_,
    )


@router.get("/analysis", response_class=HTMLResponse)
def admin_analysis_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/analysis.html",
        _analysis_page_context(
            db,
            base_path="/admin/analysis",
            selection_mode=selection_mode,
            month=month,
            period_start=period_start,
            period_end=period_end,
        ),
    )


@router.get("/conference", response_class=HTMLResponse)
def admin_conference_page(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/conference.html",
        _analysis_page_context(
            db,
            base_path="/admin/conference",
            selection_mode=selection_mode,
            month=month,
            period_start=period_start,
            period_end=period_end,
        ),
    )
