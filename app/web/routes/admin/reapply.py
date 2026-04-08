from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import (
    list_active_rules,
    preview_reapply_rules,
    reapply_rules_for_period,
    run_analysis_for_period,
)

from .helpers import is_htmx_request, parse_optional_date, render_admin, templates, trigger_admin_toast

router = APIRouter()


def _reapply_page_context(db: Session, *, reapply_result: dict | None = None) -> dict:
    return {
        "preview": None,
        "rules": list_active_rules(db),
        "reapply_result": reapply_result,
    }


def _render_reapply_shell(
    request: Request,
    db: Session,
    *,
    reapply_result: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/partials/reapply_page_shell.html",
        {
            "request": request,
            **_reapply_page_context(db, reapply_result=reapply_result),
        },
        status_code=status_code,
    )


@router.get("/reapply", response_class=HTMLResponse)
def admin_reapply_page(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    context = _reapply_page_context(db)
    if is_htmx_request(request):
        return _render_reapply_shell(request, db)
    return render_admin(request, "admin/reapply.html", context)


@router.post("/reapply/preview", response_class=HTMLResponse)
def admin_reapply_preview(
    request: Request,
    period_start: str | None = Form(default=None),
    period_end: str | None = Form(default=None),
    include_manual: bool = Form(False),
    allow_degrade_to_uncategorized: bool = Form(False),
    selected_rule_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    parsed_period_start = parse_optional_date(period_start)
    parsed_period_end = parse_optional_date(period_end)
    preview = preview_reapply_rules(
        db,
        period_start=parsed_period_start,
        period_end=parsed_period_end,
        include_manual=include_manual,
        allow_degrade_to_uncategorized=allow_degrade_to_uncategorized,
        allowed_rule_ids=selected_rule_ids or None,
    )
    return templates.TemplateResponse(
        request,
        "admin/partials/reapply_preview.html",
        {
            "request": request,
            "preview": preview,
            "period_start": parsed_period_start,
            "period_end": parsed_period_end,
            "include_manual": include_manual,
            "allow_degrade_to_uncategorized": allow_degrade_to_uncategorized,
            "selected_rule_ids": selected_rule_ids,
        },
    )


@router.post("/reapply")
def admin_reapply(
    request: Request,
    period_start: str | None = Form(default=None),
    period_end: str | None = Form(default=None),
    include_manual: bool = Form(False),
    allow_degrade_to_uncategorized: bool = Form(False),
    run_analysis_after: bool = Form(False),
    selected_rule_ids: list[int] = Form(default=[]),
    selected_transaction_ids: list[int] = Form(default=[]),
    selection_present: bool = Form(False),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    parsed_period_start = parse_optional_date(period_start)
    parsed_period_end = parse_optional_date(period_end)
    result = reapply_rules_for_period(
        db,
        period_start=parsed_period_start,
        period_end=parsed_period_end,
        include_manual=include_manual,
        allow_degrade_to_uncategorized=allow_degrade_to_uncategorized,
        allowed_rule_ids=selected_rule_ids or None,
        selected_transaction_ids=selected_transaction_ids if selection_present else None,
    )
    analysis_message = ""
    if run_analysis_after and parsed_period_start and parsed_period_end:
        run_analysis_for_period(db, period_start=parsed_period_start, period_end=parsed_period_end)
        analysis_message = " Nova análise gerada para o período informado."
    elif run_analysis_after:
        analysis_message = " Nova análise não foi gerada porque aplicar na base toda não define um período único."
    message = f"Reaplicação concluída: {result['updated_count']} alterados de {result['checked_count']} avaliados.{analysis_message}"
    if is_htmx_request(request):
        response = _render_reapply_shell(
            request,
            db,
            reapply_result={
                "updated_count": result["updated_count"],
                "checked_count": result["checked_count"],
                "analysis_message": analysis_message.strip(),
            },
        )
        return trigger_admin_toast(response, message, level="success")
    request.session["flash"] = message
    return RedirectResponse(url="/admin/reapply", status_code=303)


@router.post("/analysis/run")
def admin_run_analysis(
    request: Request,
    period_start: str = Form(...),
    period_end: str = Form(...),
    return_to: str = Form("/admin"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    parsed_period_start = parse_optional_date(period_start)
    parsed_period_end = parse_optional_date(period_end)
    run = run_analysis_for_period(db, period_start=parsed_period_start, period_end=parsed_period_end)
    request.session["flash"] = f"Nova análise gerada (run #{run.id})."
    return RedirectResponse(url=unquote(return_to), status_code=303)
