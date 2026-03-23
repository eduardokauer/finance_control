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
    analysis_data = payload_snapshot or live_snapshot
    html_fragment = renderable_analysis_html(analysis_run.html_output) if analysis_run else None
    return render_admin(
        request,
        "admin/analysis.html",
        {
            "selection_mode": selected_mode,
            "period_start": resolved_start,
            "period_end": resolved_end,
            "month_value": month_value,
            "latest_closed_start": latest_closed_start,
            "latest_closed_end": latest_closed_end,
            "month_preview_start": month_preview_start,
            "month_preview_end": month_preview_end,
            "summary": analysis_data["summary"],
            "analysis_run": analysis_run,
            "analysis_data": analysis_data,
            "analysis_html_fragment": html_fragment,
            "llm_html_available": False,
        },
    )
