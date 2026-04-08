from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, quote, unquote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.repositories.models import CreditCardInvoiceItem, Transaction
from app.services.admin import (
    delete_category_if_unused,
    list_available_analysis_months,
    list_categories,
    list_category_management_summaries,
    reassign_category_references,
    resolve_analysis_period,
    upsert_category,
)
from app.services.analysis import (
    _analysis_category_name,
    build_analysis_snapshot,
    build_category_composition_for_period,
    build_category_consumption_monthly_series,
    format_currency_br,
    format_date_br,
)
from app.services.credit_card_bills import (
    CreditCardInvoiceCategoryEditError,
    apply_manual_credit_card_invoice_item_category_change,
    get_credit_card_invoice_item_category_editor,
)
from app.utils.normalization import normalize_description

from .helpers import render_admin, templates

router = APIRouter()


def _normalize_focus_category(value: str | None) -> str:
    return normalize_description(" ".join((value or "").split()))


def _summarize_selected_categories(category_names: list[str]) -> str:
    if not category_names:
        return "Todas as categorias"
    if len(category_names) == 1:
        return category_names[0]
    if len(category_names) == 2:
        return f"{category_names[0]} + {category_names[1]}"
    return f"{category_names[0]} +{len(category_names) - 1}"


def _transaction_category_scope(transaction_kind: str | None) -> str:
    if transaction_kind == "income":
        return "income"
    if transaction_kind == "transfer":
        return "transfer"
    return "expense"


def _inline_transaction_category_options(db: Session, *, transaction_kind: str | None) -> list[dict]:
    compatible_kind = _transaction_category_scope(transaction_kind)
    return [
        {
            "value": category.name,
            "label": category.name,
        }
        for category in list_categories(db)
        if category.is_active and category.transaction_kind == compatible_kind
    ]


def _build_inline_row_common_context(
    *,
    row_dom_id: str,
    date_value: date,
    description: str,
    category_name: str,
    source_label: str,
    scope_label: str,
    amount: float,
    amount_display: str,
    detail: str,
) -> dict:
    return {
        "row_dom_id": row_dom_id,
        "date": date_value,
        "date_display": format_date_br(date_value),
        "description": description,
        "category_name": category_name,
        "source_label": source_label,
        "scope_label": scope_label,
        "amount": amount,
        "amount_display": amount_display,
        "detail": detail,
        "sort_date": date_value.isoformat(),
        "sort_description": description.casefold(),
        "sort_category": category_name.casefold(),
        "sort_source": source_label.casefold(),
        "sort_scope": scope_label.casefold(),
        "sort_amount": f"{amount:.2f}",
    }


def _build_transaction_row_context(
    db: Session,
    tx: Transaction,
    *,
    return_to: str,
    editing: bool = False,
    form_error: str | None = None,
    selected_category: str | None = None,
) -> dict:
    current_category_name = _analysis_category_name(tx.category)
    amount = abs(float(tx.amount)) if float(tx.amount) < 0 else float(tx.amount)
    options = _inline_transaction_category_options(db, transaction_kind=tx.transaction_kind)
    selected_value = (selected_category or current_category_name).strip()
    encoded_return_to = quote(return_to, safe="")
    row = _build_inline_row_common_context(
        row_dom_id=f"category-composition-row-transaction-{tx.id}",
        date_value=tx.transaction_date,
        description=tx.description_raw,
        category_name=current_category_name,
        source_label="Extrato",
        scope_label="Conta",
        amount=amount,
        amount_display=format_currency_br(amount),
        detail=tx.transaction_kind,
    )
    row.update(
        {
            "edit_href": f"/admin/transactions/{tx.id}?return_to={encoded_return_to}",
            "edit_label": "Editar lançamento",
            "inline_edit_supported": bool(options),
            "inline_edit_href": (
                f"/admin/categories/composition/transactions/{tx.id}/edit?return_to={encoded_return_to}"
            ),
            "inline_cancel_href": (
                f"/admin/categories/composition/transactions/{tx.id}/row?return_to={encoded_return_to}"
            ),
            "inline_apply_href": f"/admin/categories/composition/transactions/{tx.id}/edit",
            "inline_editing": editing,
            "inline_form_error": form_error,
            "inline_selected_category": selected_value,
            "inline_category_options": [
                {
                    **option,
                    "is_selected": option["value"] == selected_value,
                }
                for option in options
            ],
            "inline_help_text": (
                f"Tipo fixo nesta edicao: {tx.transaction_kind}. "
                "Para mudar tipo ou regra, use Editar lancamento."
            ),
            "return_to": return_to,
        }
    )
    return row


def _build_invoice_item_row_context(
    db: Session,
    *,
    invoice_id: int,
    item_id: int,
    return_to: str,
    editing: bool = False,
    form_error: str | None = None,
    selected_category: str | None = None,
) -> dict:
    editor = get_credit_card_invoice_item_category_editor(db, invoice_id=invoice_id, item_id=item_id)
    if editor is None:
        raise HTTPException(status_code=404, detail="Invoice item not found")
    item = editor.item
    current_category_name = _analysis_category_name(item.category)
    amount = float(item.amount_brl)
    encoded_return_to = quote(return_to, safe="")
    row = _build_inline_row_common_context(
        row_dom_id=f"category-composition-row-invoice-item-{item.id}",
        date_value=item.purchase_date,
        description=item.description_raw,
        category_name=current_category_name,
        source_label="Fatura",
        scope_label=f"Fatura #{editor.invoice.id}",
        amount=amount,
        amount_display=format_currency_br(amount),
        detail="charge conciliado",
    )
    selected_value = (selected_category or current_category_name).strip()
    inline_edit_supported = editor.item_type == "charge" and bool(editor.available_categories)
    row.update(
        {
            "edit_href": (
                f"/admin/credit-card-invoices/{editor.invoice.id}/items/{item.id}/category"
                f"?return_to={encoded_return_to}"
            ),
            "edit_label": "Editar categoria",
            "inline_edit_supported": inline_edit_supported,
            "inline_edit_href": (
                f"/admin/categories/composition/invoice-items/{item.id}/edit?return_to={encoded_return_to}"
            ),
            "inline_cancel_href": (
                f"/admin/categories/composition/invoice-items/{item.id}/row?return_to={encoded_return_to}"
            ),
            "inline_apply_href": f"/admin/categories/composition/invoice-items/{item.id}/edit",
            "inline_editing": editing,
            "inline_form_error": form_error,
            "inline_selected_category": selected_value,
            "inline_category_options": [
                {
                    "value": category.name,
                    "label": category.name,
                    "is_selected": category.name == selected_value,
                }
                for category in editor.available_categories
            ],
            "inline_help_text": (
                "Ajuste pontual somente deste item. "
                "Para aplicar na base com regra, use Editar categoria."
            ),
            "return_to": return_to,
        }
    )
    return row


def _render_category_composition_row(request: Request, row: dict, *, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/partials/category_composition_row.html",
        {
            "request": request,
            "row": row,
        },
        status_code=status_code,
    )


def _resolve_invoice_item_editor(db: Session, *, item_id: int):
    item = db.get(CreditCardInvoiceItem, item_id)
    if item is None:
        return None
    return get_credit_card_invoice_item_category_editor(db, invoice_id=item.invoice_id, item_id=item_id)


def _enrich_category_composition_rows(db: Session, rows: list[dict], *, return_to: str) -> None:
    for row in rows:
        if row.get("edit_kind") == "transaction" and row.get("transaction_id"):
            tx = db.get(Transaction, row["transaction_id"])
            if tx is None:
                continue
            enriched = _build_transaction_row_context(
                db,
                tx,
                return_to=return_to,
            )
        elif row.get("edit_kind") == "invoice_item" and row.get("invoice_id") and row.get("item_id"):
            enriched = _build_invoice_item_row_context(
                db,
                invoice_id=row["invoice_id"],
                item_id=row["item_id"],
                return_to=return_to,
            )
        else:
            row["edit_href"] = None
            row["edit_label"] = None
            row["inline_edit_supported"] = False
            continue
        row.update(enriched)


def _validate_inline_transaction_category(
    db: Session,
    *,
    tx: Transaction,
    category_name: str,
) -> str:
    normalized_name = (category_name or "").strip()
    valid_names = {
        option["value"]
        for option in _inline_transaction_category_options(db, transaction_kind=tx.transaction_kind)
    }
    if normalized_name not in valid_names:
        raise ValueError("Categoria invalida para este lancamento.")
    return normalized_name


def _category_still_matches_current_context(*, category_name: str, return_to: str) -> bool:
    query = parse_qs(urlsplit(return_to).query)
    selected_names = query.get("selected_category") or query.get("focus_category") or []
    if not selected_names:
        return True
    selected_keys = {_normalize_focus_category(name) for name in selected_names if name}
    return _normalize_focus_category(category_name) in selected_keys


def _categories_page_context(
    db: Session,
    *,
    selection_mode: str | None,
    month: str | None,
    period_start: date | None,
    period_end: date | None,
    focus_category: str | None,
    selected_categories: list[str] | None,
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
    elif period_start and period_end:
        resolved_start, resolved_end = resolve_analysis_period(
            db,
            month=None,
            period_start=period_start,
            period_end=period_end,
        )
        if selected_mode == "closed" and (resolved_start != latest_closed_start or resolved_end != latest_closed_end):
            selected_mode = "custom"
    else:
        resolved_start, resolved_end = latest_closed_start, latest_closed_end

    analysis_data = build_analysis_snapshot(
        db,
        period_start=resolved_start,
        period_end=resolved_end,
    )
    all_categories = list_categories(db)
    available_categories = [
        category
        for category in all_categories
        if category.transaction_kind == "expense" and category.is_active
    ]
    available_category_names = [category.name for category in available_categories]

    ranking_rows = [
        row
        for row in analysis_data["category_breakdown"]["rows"]
        if row["expense_total"] > 0 and not row["is_technical"]
    ]
    ranking_rows.sort(key=lambda item: item["expense_total"], reverse=True)

    explicit_selected_category_keys = {
        _normalize_focus_category(category_name)
        for category_name in (selected_categories or [])
        if category_name
    }
    selected_category_keys = set(explicit_selected_category_keys)
    if not selected_category_keys and focus_category:
        selected_category_keys.add(_normalize_focus_category(focus_category))

    selected_category_names = [
        category_name
        for category_name in available_category_names
        if _normalize_focus_category(category_name) in selected_category_keys
    ]
    selected_category_name_keys = {
        _normalize_focus_category(category_name)
        for category_name in selected_category_names
    }
    filtered_ranking_rows = [
        row
        for row in ranking_rows
        if not selected_category_names or _normalize_focus_category(row["name"]) in selected_category_name_keys
    ]

    normalized_focus = _normalize_focus_category(focus_category)
    valid_focus = next(
        (row["name"] for row in filtered_ranking_rows if _normalize_focus_category(row["name"]) == normalized_focus),
        None,
    )
    composition_categories = selected_category_names or ([valid_focus] if valid_focus else None)
    composition = (
        build_category_composition_for_period(
            db,
            period_start=resolved_start,
            period_end=resolved_end,
            category_names=composition_categories,
        )
        if composition_categories or available_category_names
        else None
    )

    category_filter_options = [
        {
            "value": category.name,
            "label": category.name,
            "is_selected": category.name in selected_category_names,
        }
        for category in available_categories
    ]
    filtered_consumption_chart = build_category_consumption_monthly_series(
        db,
        anchor_month=resolved_end,
        category_names=selected_category_names or None,
    )
    all_categories_selected = bool(available_category_names) and len(selected_category_names) == len(available_category_names)
    selected_categories_summary = (
        "Todas as categorias"
        if all_categories_selected or not selected_category_names
        else _summarize_selected_categories(selected_category_names)
    )

    latest_closed_value = f"{latest_closed_start.year:04d}-{latest_closed_start.month:02d}"
    analysis_month_options = list_available_analysis_months(db)
    latest_closed_label = next(
        (option["label"] for option in analysis_month_options if option["value"] == latest_closed_value),
        latest_closed_value,
    )

    return {
        "selection_mode": selected_mode,
        "period_start": resolved_start,
        "period_end": resolved_end,
        "month_value": month_value,
        "latest_closed_start": latest_closed_start,
        "latest_closed_end": latest_closed_end,
        "month_preview_start": month_preview_start,
        "month_preview_end": month_preview_end,
        "analysis_month_options": analysis_month_options,
        "latest_closed_label": latest_closed_label,
        "analysis_breadcrumb_items": [{"label": "Categorias", "href": None}],
        "analysis_back_href": None,
        "analysis_context_chips": [
            {"key": "period", "label": "Período", "value": analysis_data["period"]["label"]},
            *(
                [{"key": "focus_category", "label": "Categoria em foco", "value": valid_focus}]
                if valid_focus
                else []
            ),
            {
                "key": "selected_categories",
                "label": "Categorias",
                "value": selected_categories_summary,
            },
        ],
        "analysis_focus_banner": (
            {
                "key": "categories",
                "title": "Composição aberta a partir da overview",
                "body": (
                    f"A composição de {valid_focus} foi restaurada com o mesmo período do clique, "
                    "combinando conta e charges conciliados de fatura."
                ),
                "href": "#category-composition-section",
                "link_label": "Ir para a composição",
            }
            if valid_focus
            else None
        ),
        "analysis_form_action": "/admin/categories",
        "analysis_submit_label": "Ver categorias",
        "analysis_show_generate": False,
        "analysis_global_tabs": [],
        "analysis_controls_intro": (
            "Categorias vira uma área própria: o filtro define o período da leitura, do gráfico principal "
            "e da composição clicável."
        ),
        "analysis_toolbar_filters": [
            {
                "kind": "multi_select_dropdown",
                "name": "selected_category",
                "label": "Selecionar categorias",
                "summary": selected_categories_summary,
                "options": category_filter_options,
                "actions": [
                    {"key": "select_all", "label": "Selecionar todas"},
                    {"key": "clear_all", "label": "Limpar selecao"},
                ],
            }
        ],
        "analysis_extra_hidden_fields": [
            {"name": "focus_category", "value": valid_focus, "clear_on_empty": True},
        ],
        "categories": all_categories,
        "category_breakdown": analysis_data["category_breakdown"],
        "category_composition": composition,
        "consumption_chart": filtered_consumption_chart,
    }


def _categories_management_context(
    db: Session,
    *,
    request_url: str,
    management_error: str | None = None,
    reassign_source_category_id: int | None = None,
    reassign_target_category_id: int | None = None,
) -> dict:
    all_categories = list_categories(db)
    category_summaries = list_category_management_summaries(db)
    summary_by_category_id = {
        summary.category.id: summary
        for summary in category_summaries
    }
    category_rows = []
    for category in all_categories:
        summary = summary_by_category_id.get(category.id)
        usage = summary.usage if summary is not None else None
        move_target_options = [
            {
                "id": other.id,
                "name": other.name,
            }
            for other in all_categories
            if other.id != category.id and other.is_active and other.transaction_kind == category.transaction_kind
        ]
        category_rows.append(
            {
                "category": category,
                "transactions_count": usage.transactions_count if usage else 0,
                "invoice_items_count": usage.invoice_items_count if usage else 0,
                "rules_count": usage.rules_count if usage else 0,
                "total_references": usage.total_references if usage else 0,
                "can_delete": summary.can_delete if summary is not None else False,
                "delete_block_reason": summary.delete_block_reason if summary is not None else None,
                "move_target_options": move_target_options,
                "selected_move_target_id": (
                    reassign_target_category_id
                    if reassign_source_category_id == category.id
                    else None
                ),
            }
        )
    return {
        "categories": all_categories,
        "category_management_rows": category_rows,
        "management_return_to": request_url,
        "management_error": management_error,
    }


@router.get("/categories", response_class=HTMLResponse)
def admin_categories(
    request: Request,
    selection_mode: str | None = None,
    month: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    focus_category: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    selected_categories = request.query_params.getlist("selected_category")
    context = _categories_page_context(
        db,
        selection_mode=selection_mode,
        month=month,
        period_start=period_start,
        period_end=period_end,
        focus_category=focus_category,
        selected_categories=selected_categories,
    )
    current_relative_url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    encoded_return_to = quote(current_relative_url, safe="")
    composition = context.get("category_composition")
    if composition:
        for row in composition.get("rows", []):
            if row.get("edit_kind") == "transaction" and row.get("transaction_id"):
                row["edit_href"] = f"/admin/transactions/{row['transaction_id']}?return_to={encoded_return_to}"
                row["edit_label"] = "Editar lançamento"
            elif row.get("edit_kind") == "invoice_item" and row.get("invoice_id") and row.get("item_id"):
                row["edit_href"] = (
                    f"/admin/credit-card-invoices/{row['invoice_id']}/items/{row['item_id']}/category"
                    f"?return_to={encoded_return_to}"
                )
                row["edit_label"] = "Editar categoria"
            else:
                row["edit_href"] = None
                row["edit_label"] = None
    if composition:
        _enrich_category_composition_rows(
            db,
            composition.get("rows", []),
            return_to=current_relative_url,
        )
    return render_admin(
        request,
        "admin/categories.html",
        context,
    )


@router.get("/categories/composition/transactions/{transaction_id}/row", response_class=HTMLResponse)
def admin_category_composition_transaction_row(
    transaction_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _render_category_composition_row(
        request,
        _build_transaction_row_context(
            db,
            tx,
            return_to=unquote(return_to or "/admin/categories"),
        ),
    )


@router.get("/categories/composition/transactions/{transaction_id}/edit", response_class=HTMLResponse)
def admin_category_composition_transaction_row_edit(
    transaction_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _render_category_composition_row(
        request,
        _build_transaction_row_context(
            db,
            tx,
            return_to=unquote(return_to or "/admin/categories"),
            editing=True,
        ),
    )


@router.post("/categories/composition/transactions/{transaction_id}/edit", response_class=HTMLResponse)
def admin_category_composition_transaction_row_apply(
    transaction_id: int,
    request: Request,
    category: str = Form(...),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    resolved_return_to = unquote(return_to or "/admin/categories")
    try:
        selected_category = _validate_inline_transaction_category(
            db,
            tx=tx,
            category_name=category,
        )
    except ValueError as exc:
        return _render_category_composition_row(
            request,
            _build_transaction_row_context(
                db,
                tx,
                return_to=resolved_return_to,
                editing=True,
                form_error=str(exc),
                selected_category=category,
            ),
            status_code=422,
        )

    from app.services.admin import reclassify_transactions_manual

    reclassify_transactions_manual(
        db,
        [tx],
        category=selected_category,
        transaction_kind=tx.transaction_kind,
        notes="Edicao inline na composicao de categorias.",
        origin="category_composition_inline",
    )
    db.refresh(tx)
    if not _category_still_matches_current_context(category_name=tx.category or "", return_to=resolved_return_to):
        return HTMLResponse("")
    return _render_category_composition_row(
        request,
        _build_transaction_row_context(
            db,
            tx,
            return_to=resolved_return_to,
        ),
    )


@router.get("/categories/composition/invoice-items/{item_id}/row", response_class=HTMLResponse)
def admin_category_composition_invoice_item_row(
    item_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    editor = _resolve_invoice_item_editor(db, item_id=item_id)
    if editor is None:
        raise HTTPException(status_code=404, detail="Invoice item not found")
    return _render_category_composition_row(
        request,
        _build_invoice_item_row_context(
            db,
            invoice_id=editor.invoice.id,
            item_id=item_id,
            return_to=unquote(return_to or "/admin/categories"),
        ),
    )


@router.get("/categories/composition/invoice-items/{item_id}/edit", response_class=HTMLResponse)
def admin_category_composition_invoice_item_row_edit(
    item_id: int,
    request: Request,
    return_to: str | None = None,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    editor = _resolve_invoice_item_editor(db, item_id=item_id)
    if editor is None:
        raise HTTPException(status_code=404, detail="Invoice item not found")
    return _render_category_composition_row(
        request,
        _build_invoice_item_row_context(
            db,
            invoice_id=editor.invoice.id,
            item_id=item_id,
            return_to=unquote(return_to or "/admin/categories"),
            editing=True,
        ),
    )


@router.post("/categories/composition/invoice-items/{item_id}/edit", response_class=HTMLResponse)
def admin_category_composition_invoice_item_row_apply(
    item_id: int,
    request: Request,
    category: str = Form(...),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    editor = _resolve_invoice_item_editor(db, item_id=item_id)
    if editor is None:
        raise HTTPException(status_code=404, detail="Invoice item not found")
    resolved_return_to = unquote(return_to or "/admin/categories")
    try:
        apply_manual_credit_card_invoice_item_category_change(
            db,
            invoice_id=editor.invoice.id,
            item_id=item_id,
            category_name=category,
        )
    except CreditCardInvoiceCategoryEditError as exc:
        return _render_category_composition_row(
            request,
            _build_invoice_item_row_context(
                db,
                invoice_id=editor.invoice.id,
                item_id=item_id,
                return_to=resolved_return_to,
                editing=True,
                form_error=str(exc),
                selected_category=category,
            ),
            status_code=exc.status_code,
        )
    refreshed_editor = _resolve_invoice_item_editor(db, item_id=item_id)
    if refreshed_editor is None:
        raise HTTPException(status_code=404, detail="Invoice item not found")
    if not _category_still_matches_current_context(
        category_name=refreshed_editor.item.category or "",
        return_to=resolved_return_to,
    ):
        return HTMLResponse("")
    return _render_category_composition_row(
        request,
        _build_invoice_item_row_context(
            db,
            invoice_id=refreshed_editor.invoice.id,
            item_id=item_id,
            return_to=resolved_return_to,
        ),
    )


@router.get("/categories/manage", response_class=HTMLResponse)
def admin_categories_manage(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    return render_admin(
        request,
        "admin/categories_manage.html",
        _categories_management_context(
            db,
            request_url=str(request.url),
        ),
    )


@router.post("/categories")
def admin_create_category(
    request: Request,
    name: str = Form(...),
    transaction_kind: str = Form(...),
    is_active: bool = Form(True),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    upsert_category(db, category_id=None, name=name, transaction_kind=transaction_kind, is_active=is_active)
    request.session["flash"] = "Categoria salva."
    return RedirectResponse(url=unquote(return_to or "/admin/categories/manage"), status_code=303)


@router.post("/categories/{category_id}/update")
def admin_update_category(
    category_id: int,
    request: Request,
    name: str = Form(...),
    transaction_kind: str = Form(...),
    is_active: bool = Form(False),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    upsert_category(db, category_id=category_id, name=name, transaction_kind=transaction_kind, is_active=is_active)
    request.session["flash"] = "Categoria atualizada."
    return RedirectResponse(url=unquote(return_to or "/admin/categories/manage"), status_code=303)


@router.post("/categories/{category_id}/reassign")
def admin_reassign_category(
    category_id: int,
    request: Request,
    target_category_id: int = Form(...),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    resolved_return_to = unquote(return_to or "/admin/categories/manage")
    try:
        result = reassign_category_references(
            db,
            source_category_id=category_id,
            target_category_id=target_category_id,
        )
    except ValueError as exc:
        return render_admin(
            request,
            "admin/categories_manage.html",
            _categories_management_context(
                db,
                request_url=resolved_return_to,
                management_error=str(exc),
                reassign_source_category_id=category_id,
                reassign_target_category_id=target_category_id,
            ),
            status_code=400,
        )
    request.session["flash"] = (
        f"Categoria consolidada: {result['source_category'].name} -> {result['target_category'].name}. "
        f"{result['transactions_updated']} lancamento(s), "
        f"{result['invoice_items_updated']} item(ns) de fatura e "
        f"{result['rules_updated']} regra(s) atualizados."
    )
    return RedirectResponse(url=resolved_return_to, status_code=303)


@router.post("/categories/{category_id}/delete")
def admin_delete_category(
    category_id: int,
    request: Request,
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin_session),
):
    resolved_return_to = unquote(return_to or "/admin/categories/manage")
    try:
        deleted_category = delete_category_if_unused(db, category_id=category_id)
    except ValueError as exc:
        return render_admin(
            request,
            "admin/categories_manage.html",
            _categories_management_context(
                db,
                request_url=resolved_return_to,
                management_error=str(exc),
            ),
            status_code=400,
        )
    request.session["flash"] = f"Categoria excluida: {deleted_category.name}."
    return RedirectResponse(url=resolved_return_to, status_code=303)
