from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.parsers.credit_card_bill_parser import parse_itau_credit_card_csv
from app.repositories.models import (
    CreditCard,
    CreditCardInvoice,
    CreditCardInvoiceConciliation,
    CreditCardInvoiceConciliationItem,
    CreditCardInvoiceItem,
    SourceFile,
    Transaction,
)
from app.utils.hashing import canonical_hash, file_hash
from app.utils.normalization import normalize_description


CENT_VALUE = Decimal("0.01")
CANDIDATE_WINDOW_DAYS_BEFORE = 20
CANDIDATE_WINDOW_DAYS_AFTER = 40


class CreditCardBillError(Exception):
    status_code = 422


class CreditCardBillDuplicateFileError(CreditCardBillError):
    status_code = 409


class CreditCardBillConflictError(CreditCardBillError):
    status_code = 409


class CreditCardInvoiceConciliationError(CreditCardBillError):
    status_code = 409


@dataclass
class CreditCardBillUploadInput:
    card_id: int
    billing_year: int
    billing_month: int
    due_date: date
    total_amount_brl: Decimal
    closing_date: date | None = None
    notes: str | None = None


INVOICE_IMPORT_STATUSES = ("imported", "pending_review", "conciliated", "conflict")
INVOICE_ITEM_TYPES = ("charge", "credit", "payment", "unknown")
CONCILIATION_STATUSES = ("pending_review", "partially_conciliated", "conciliated", "conflict")
CONCILIATION_ITEM_TYPES = ("bank_payment", "invoice_credit")


@dataclass
class CreditCardInvoiceListEntry:
    invoice: CreditCardInvoice
    card: CreditCard
    item_count: int


@dataclass
class CreditCardInvoiceItemDetail:
    item: CreditCardInvoiceItem
    item_type: str


@dataclass
class CreditCardInvoiceSummary:
    charge_total_brl: Decimal
    credit_total_brl: Decimal
    payment_total_brl: Decimal
    unknown_total_brl: Decimal
    composed_total_brl: Decimal
    difference_to_invoice_total_brl: Decimal
    items_total_brl: Decimal


@dataclass
class CreditCardInvoiceConciliationItemDetail:
    conciliation_item: CreditCardInvoiceConciliationItem
    bank_transaction: Transaction | None
    invoice_item: CreditCardInvoiceItem | None


@dataclass
class CreditCardInvoicePaymentCandidate:
    transaction: Transaction
    linked_invoice_id: int | None
    amount_gap_brl: Decimal
    days_from_due_date: int
    fit_label: str


@dataclass
class CreditCardInvoiceConciliationSummary:
    conciliation: CreditCardInvoiceConciliation
    gross_amount_brl: Decimal
    invoice_credit_total_brl: Decimal
    bank_payment_total_brl: Decimal
    conciliated_total_brl: Decimal
    remaining_balance_brl: Decimal
    status: str


@dataclass
class CreditCardInvoiceDetail:
    invoice: CreditCardInvoice
    card: CreditCard
    source_file: SourceFile | None
    items: list[CreditCardInvoiceItemDetail]
    item_count: int
    summary: CreditCardInvoiceSummary
    conciliation_summary: CreditCardInvoiceConciliationSummary
    conciliation_items: list[CreditCardInvoiceConciliationItemDetail]
    payment_candidates: list[CreditCardInvoicePaymentCandidate]


def _quantize(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT_VALUE)


def list_credit_cards(db: Session, *, active_only: bool = False) -> list[CreditCard]:
    query = select(CreditCard)
    if active_only:
        query = query.where(CreditCard.is_active.is_(True))
    return db.scalars(query.order_by(CreditCard.is_active.desc(), CreditCard.card_label.asc(), CreditCard.id.asc())).all()


def classify_credit_card_invoice_item(item: CreditCardInvoiceItem) -> str:
    description = (item.description_normalized or item.description_raw or "").strip().lower()
    if not description:
        return "unknown"
    if "pagamento efetuado" in description:
        return "payment"
    if "desconto na fatura" in description:
        return "credit"
    if item.amount_brl < 0:
        return "credit"
    return "charge"


def list_recent_credit_card_invoices(db: Session, *, limit: int = 10) -> list[dict]:
    item_count = func.count(CreditCardInvoiceItem.id).label("item_count")
    rows = db.execute(
        select(CreditCardInvoice, CreditCard.card_label, item_count)
        .join(CreditCard, CreditCard.id == CreditCardInvoice.card_id)
        .outerjoin(CreditCardInvoiceItem, CreditCardInvoiceItem.invoice_id == CreditCardInvoice.id)
        .group_by(CreditCardInvoice.id, CreditCard.card_label)
        .order_by(CreditCardInvoice.imported_at.desc(), CreditCardInvoice.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "invoice_id": invoice.id,
            "card_label": card_label,
            "billing_year": invoice.billing_year,
            "billing_month": invoice.billing_month,
            "due_date": invoice.due_date,
            "closing_date": invoice.closing_date,
            "total_amount_brl": invoice.total_amount_brl,
            "import_status": invoice.import_status,
            "item_count": int(item_count_value or 0),
            "imported_at": invoice.imported_at,
        }
        for invoice, card_label, item_count_value in rows
    ]


def list_credit_card_invoices(db: Session) -> list[CreditCardInvoiceListEntry]:
    item_counts = (
        select(
            CreditCardInvoiceItem.invoice_id.label("invoice_id"),
            func.count(CreditCardInvoiceItem.id).label("item_count"),
        )
        .group_by(CreditCardInvoiceItem.invoice_id)
        .subquery()
    )
    rows = db.execute(
        select(
            CreditCardInvoice,
            CreditCard,
            func.coalesce(item_counts.c.item_count, 0),
        )
        .join(CreditCard, CreditCard.id == CreditCardInvoice.card_id)
        .outerjoin(item_counts, item_counts.c.invoice_id == CreditCardInvoice.id)
        .order_by(
            CreditCardInvoice.billing_year.desc(),
            CreditCardInvoice.billing_month.desc(),
            CreditCardInvoice.due_date.desc(),
            CreditCardInvoice.id.desc(),
        )
    ).all()
    return [
        CreditCardInvoiceListEntry(invoice=invoice, card=card, item_count=int(item_count or 0))
        for invoice, card, item_count in rows
    ]


def _load_invoice_row(db: Session, *, invoice_id: int):
    return db.execute(
        select(CreditCardInvoice, CreditCard, SourceFile)
        .join(CreditCard, CreditCard.id == CreditCardInvoice.card_id)
        .outerjoin(SourceFile, SourceFile.id == CreditCardInvoice.source_file_id)
        .where(CreditCardInvoice.id == invoice_id)
    ).one_or_none()


def _load_invoice_item_details(db: Session, *, invoice_id: int) -> list[CreditCardInvoiceItemDetail]:
    items = db.scalars(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice_id)
        .order_by(CreditCardInvoiceItem.purchase_date.asc(), CreditCardInvoiceItem.id.asc())
    ).all()
    return [CreditCardInvoiceItemDetail(item=item, item_type=classify_credit_card_invoice_item(item)) for item in items]


def _build_invoice_summary(
    *,
    item_details: list[CreditCardInvoiceItemDetail],
    invoice_total_brl: Decimal,
) -> CreditCardInvoiceSummary:
    charge_total_brl = sum(
        (item_detail.item.amount_brl for item_detail in item_details if item_detail.item_type == "charge"),
        Decimal("0.00"),
    )
    credit_total_brl = sum(
        (item_detail.item.amount_brl for item_detail in item_details if item_detail.item_type == "credit"),
        Decimal("0.00"),
    )
    payment_total_brl = sum(
        (item_detail.item.amount_brl for item_detail in item_details if item_detail.item_type == "payment"),
        Decimal("0.00"),
    )
    unknown_total_brl = sum(
        (item_detail.item.amount_brl for item_detail in item_details if item_detail.item_type == "unknown"),
        Decimal("0.00"),
    )
    items_total_brl = sum((item_detail.item.amount_brl for item_detail in item_details), Decimal("0.00"))
    composed_total_brl = charge_total_brl + credit_total_brl
    difference_to_invoice_total_brl = _quantize(invoice_total_brl - composed_total_brl)
    return CreditCardInvoiceSummary(
        charge_total_brl=_quantize(charge_total_brl),
        credit_total_brl=_quantize(credit_total_brl),
        payment_total_brl=_quantize(payment_total_brl),
        unknown_total_brl=_quantize(unknown_total_brl),
        composed_total_brl=_quantize(composed_total_brl),
        difference_to_invoice_total_brl=difference_to_invoice_total_brl,
        items_total_brl=_quantize(items_total_brl),
    )


def _candidate_window(invoice: CreditCardInvoice) -> tuple[date, date]:
    return (
        invoice.due_date - timedelta(days=CANDIDATE_WINDOW_DAYS_BEFORE),
        invoice.due_date + timedelta(days=CANDIDATE_WINDOW_DAYS_AFTER),
    )


def _payment_description_predicate() -> tuple:
    return (
        Transaction.is_card_bill_payment.is_(True),
        Transaction.description_normalized.contains("pagamento"),
        Transaction.description_normalized.contains("fatura"),
        Transaction.description_normalized.contains("cartao"),
        Transaction.description_normalized.contains("itaucard"),
        Transaction.description_normalized.contains("card"),
    )


def _looks_like_invoice_payment(transaction: Transaction, invoice: CreditCardInvoice) -> bool:
    description = transaction.description_normalized or normalize_description(transaction.description_raw or "")
    if any(token in description for token in ("pagamento", "fatura", "cartao", "itaucard", "card")):
        return True
    issuer = normalize_description(invoice.issuer or "")
    return bool(issuer and issuer in description and ("cartao" in description or "fatura" in description))


def _get_or_create_conciliation(
    db: Session,
    *,
    invoice: CreditCardInvoice,
    item_details: list[CreditCardInvoiceItemDetail],
) -> CreditCardInvoiceConciliation:
    conciliation = db.scalar(
        select(CreditCardInvoiceConciliation).where(CreditCardInvoiceConciliation.invoice_id == invoice.id)
    )
    if conciliation is None:
        conciliation = CreditCardInvoiceConciliation(
            invoice_id=invoice.id,
            status="pending_review",
            gross_amount_brl=Decimal("0.00"),
            invoice_credit_total_brl=Decimal("0.00"),
            bank_payment_total_brl=Decimal("0.00"),
            conciliated_total_brl=Decimal("0.00"),
            remaining_balance_brl=Decimal("0.00"),
        )
        db.add(conciliation)
        db.flush()

    credit_items = {item_detail.item.id: item_detail for item_detail in item_details if item_detail.item_type == "credit"}
    existing_credit_items = {
        item.invoice_item_id: item
        for item in db.scalars(
            select(CreditCardInvoiceConciliationItem).where(
                CreditCardInvoiceConciliationItem.conciliation_id == conciliation.id,
                CreditCardInvoiceConciliationItem.item_type == "invoice_credit",
            )
        ).all()
        if item.invoice_item_id is not None
    }

    for invoice_item_id, item_detail in credit_items.items():
        amount_brl = _quantize(abs(item_detail.item.amount_brl))
        existing = existing_credit_items.pop(invoice_item_id, None)
        if existing is None:
            db.add(
                CreditCardInvoiceConciliationItem(
                    conciliation_id=conciliation.id,
                    item_type="invoice_credit",
                    amount_brl=amount_brl,
                    invoice_item_id=item_detail.item.id,
                    notes="Auto-added from invoice credit item.",
                )
            )
            continue
        if existing.amount_brl != amount_brl:
            existing.amount_brl = amount_brl

    for stale_item in existing_credit_items.values():
        db.delete(stale_item)

    db.flush()
    _recalculate_conciliation(db, conciliation=conciliation, item_details=item_details)
    db.flush()
    return conciliation


def _recalculate_conciliation(
    db: Session,
    *,
    conciliation: CreditCardInvoiceConciliation,
    item_details: list[CreditCardInvoiceItemDetail],
) -> None:
    gross_amount_brl = sum(
        (item_detail.item.amount_brl for item_detail in item_details if item_detail.item_type == "charge"),
        Decimal("0.00"),
    )

    rows = db.execute(
        select(CreditCardInvoiceConciliationItem)
        .where(CreditCardInvoiceConciliationItem.conciliation_id == conciliation.id)
        .order_by(CreditCardInvoiceConciliationItem.id.asc())
    ).scalars().all()

    invoice_credit_total_brl = sum(
        (item.amount_brl for item in rows if item.item_type == "invoice_credit"),
        Decimal("0.00"),
    )
    bank_payment_total_brl = sum(
        (item.amount_brl for item in rows if item.item_type == "bank_payment"),
        Decimal("0.00"),
    )
    conciliated_total_brl = invoice_credit_total_brl + bank_payment_total_brl
    remaining_balance_brl = gross_amount_brl - conciliated_total_brl

    gross_amount_brl = _quantize(gross_amount_brl)
    invoice_credit_total_brl = _quantize(invoice_credit_total_brl)
    bank_payment_total_brl = _quantize(bank_payment_total_brl)
    conciliated_total_brl = _quantize(conciliated_total_brl)
    remaining_balance_brl = _quantize(remaining_balance_brl)

    if remaining_balance_brl < Decimal("0.00"):
        status = "conflict"
    elif remaining_balance_brl == Decimal("0.00") and conciliated_total_brl > Decimal("0.00"):
        status = "conciliated"
    elif conciliated_total_brl > Decimal("0.00") and remaining_balance_brl > Decimal("0.00"):
        status = "partially_conciliated"
    else:
        status = "pending_review"

    conciliation.status = status
    conciliation.gross_amount_brl = gross_amount_brl
    conciliation.invoice_credit_total_brl = invoice_credit_total_brl
    conciliation.bank_payment_total_brl = bank_payment_total_brl
    conciliation.conciliated_total_brl = conciliated_total_brl
    conciliation.remaining_balance_brl = remaining_balance_brl


def _load_conciliation_item_details(
    db: Session,
    *,
    conciliation_id: int,
) -> list[CreditCardInvoiceConciliationItemDetail]:
    rows = db.execute(
        select(
            CreditCardInvoiceConciliationItem,
            Transaction,
            CreditCardInvoiceItem,
        )
        .outerjoin(Transaction, Transaction.id == CreditCardInvoiceConciliationItem.bank_transaction_id)
        .outerjoin(CreditCardInvoiceItem, CreditCardInvoiceItem.id == CreditCardInvoiceConciliationItem.invoice_item_id)
        .where(CreditCardInvoiceConciliationItem.conciliation_id == conciliation_id)
        .order_by(CreditCardInvoiceConciliationItem.created_at.asc(), CreditCardInvoiceConciliationItem.id.asc())
    ).all()
    return [
        CreditCardInvoiceConciliationItemDetail(
            conciliation_item=conciliation_item,
            bank_transaction=bank_transaction,
            invoice_item=invoice_item,
        )
        for conciliation_item, bank_transaction, invoice_item in rows
    ]


def list_invoice_payment_candidates(
    db: Session,
    *,
    invoice: CreditCardInvoice,
    conciliation: CreditCardInvoiceConciliation,
) -> list[CreditCardInvoicePaymentCandidate]:
    start_date, end_date = _candidate_window(invoice)
    linked_transactions = (
        select(
            CreditCardInvoiceConciliationItem.bank_transaction_id.label("bank_transaction_id"),
            CreditCardInvoiceConciliation.invoice_id.label("linked_invoice_id"),
        )
        .join(
            CreditCardInvoiceConciliation,
            CreditCardInvoiceConciliation.id == CreditCardInvoiceConciliationItem.conciliation_id,
        )
        .where(CreditCardInvoiceConciliationItem.bank_transaction_id.is_not(None))
        .subquery()
    )

    rows = db.execute(
        select(Transaction, linked_transactions.c.linked_invoice_id)
        .outerjoin(linked_transactions, linked_transactions.c.bank_transaction_id == Transaction.id)
        .where(
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
            or_(Transaction.direction == "debit", Transaction.amount < 0),
            or_(*_payment_description_predicate()),
        )
        .order_by(Transaction.transaction_date.desc(), func.abs(Transaction.amount).desc(), Transaction.id.desc())
    ).all()

    candidates: list[CreditCardInvoicePaymentCandidate] = []
    for transaction, linked_invoice_id in rows:
        if not _looks_like_invoice_payment(transaction, invoice):
            continue
        if linked_invoice_id == invoice.id:
            continue
        amount_brl = _quantize(abs(Decimal(str(transaction.amount))))
        amount_gap_brl = _quantize(abs(conciliation.remaining_balance_brl - amount_brl))
        days_from_due_date = abs((transaction.transaction_date - invoice.due_date).days)
        if amount_brl == conciliation.remaining_balance_brl:
            fit_label = "match_saldo"
        elif amount_brl == _quantize(invoice.total_amount_brl):
            fit_label = "match_total"
        elif amount_gap_brl <= Decimal("5.00"):
            fit_label = "proximo_do_saldo"
        else:
            fit_label = "candidato"
        candidates.append(
            CreditCardInvoicePaymentCandidate(
                transaction=transaction,
                linked_invoice_id=linked_invoice_id,
                amount_gap_brl=amount_gap_brl,
                days_from_due_date=days_from_due_date,
                fit_label=fit_label,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            1 if candidate.linked_invoice_id is not None else 0,
            candidate.amount_gap_brl,
            candidate.days_from_due_date,
            -candidate.transaction.id,
        )
    )
    return candidates


def ensure_credit_card_invoice_conciliation(
    db: Session,
    *,
    invoice_id: int,
) -> CreditCardInvoiceConciliation | None:
    row = _load_invoice_row(db, invoice_id=invoice_id)
    if row is None:
        return None
    invoice, _, _ = row
    item_details = _load_invoice_item_details(db, invoice_id=invoice_id)
    conciliation = _get_or_create_conciliation(db, invoice=invoice, item_details=item_details)
    db.commit()
    db.refresh(conciliation)
    return conciliation


def get_credit_card_invoice_detail(db: Session, *, invoice_id: int) -> CreditCardInvoiceDetail | None:
    row = _load_invoice_row(db, invoice_id=invoice_id)
    if row is None:
        return None

    invoice, card, source_file = row
    item_details = _load_invoice_item_details(db, invoice_id=invoice.id)
    conciliation = _get_or_create_conciliation(db, invoice=invoice, item_details=item_details)
    db.commit()
    db.refresh(conciliation)

    summary = _build_invoice_summary(item_details=item_details, invoice_total_brl=invoice.total_amount_brl)
    conciliation_items = _load_conciliation_item_details(db, conciliation_id=conciliation.id)
    payment_candidates = list_invoice_payment_candidates(db, invoice=invoice, conciliation=conciliation)

    return CreditCardInvoiceDetail(
        invoice=invoice,
        card=card,
        source_file=source_file,
        items=item_details,
        item_count=len(item_details),
        summary=summary,
        conciliation_summary=CreditCardInvoiceConciliationSummary(
            conciliation=conciliation,
            gross_amount_brl=conciliation.gross_amount_brl,
            invoice_credit_total_brl=conciliation.invoice_credit_total_brl,
            bank_payment_total_brl=conciliation.bank_payment_total_brl,
            conciliated_total_brl=conciliation.conciliated_total_brl,
            remaining_balance_brl=conciliation.remaining_balance_brl,
            status=conciliation.status,
        ),
        conciliation_items=conciliation_items,
        payment_candidates=payment_candidates,
    )


def reconcile_credit_card_invoice_bank_payments(
    db: Session,
    *,
    invoice_id: int,
    bank_transaction_ids: list[int],
) -> CreditCardInvoiceConciliation:
    if not bank_transaction_ids:
        raise CreditCardInvoiceConciliationError("Selecione ao menos um pagamento do extrato.")

    row = _load_invoice_row(db, invoice_id=invoice_id)
    if row is None:
        raise CreditCardInvoiceConciliationError("Fatura nao encontrada.")

    invoice, _, _ = row
    item_details = _load_invoice_item_details(db, invoice_id=invoice.id)
    conciliation = _get_or_create_conciliation(db, invoice=invoice, item_details=item_details)
    candidate_map = {
        candidate.transaction.id: candidate
        for candidate in list_invoice_payment_candidates(db, invoice=invoice, conciliation=conciliation)
    }
    existing_current_payment_ids = {
        item.bank_transaction_id
        for item in db.scalars(
            select(CreditCardInvoiceConciliationItem).where(
                CreditCardInvoiceConciliationItem.conciliation_id == conciliation.id,
                CreditCardInvoiceConciliationItem.item_type == "bank_payment",
                CreditCardInvoiceConciliationItem.bank_transaction_id.is_not(None),
            )
        ).all()
    }

    selected_ids = list(dict.fromkeys(bank_transaction_ids))
    selected_total_brl = Decimal("0.00")
    for transaction_id in selected_ids:
        if transaction_id in existing_current_payment_ids:
            continue
        candidate = candidate_map.get(transaction_id)
        if candidate is None:
            raise CreditCardInvoiceConciliationError("Pagamento selecionado nao e um candidato valido para esta fatura.")
        if candidate.linked_invoice_id is not None and candidate.linked_invoice_id != invoice.id:
            raise CreditCardInvoiceConciliationError("Transacao bancaria ja conciliada em outra fatura.")
        selected_total_brl += _quantize(abs(Decimal(str(candidate.transaction.amount))))

    projected_total = conciliation.conciliated_total_brl + selected_total_brl
    if projected_total - conciliation.gross_amount_brl > Decimal("0.00"):
        raise CreditCardInvoiceConciliationError("A soma selecionada ultrapassa o saldo esperado da fatura.")

    for transaction_id in selected_ids:
        if transaction_id in existing_current_payment_ids:
            continue
        transaction = candidate_map[transaction_id].transaction
        db.add(
            CreditCardInvoiceConciliationItem(
                conciliation_id=conciliation.id,
                item_type="bank_payment",
                amount_brl=_quantize(abs(Decimal(str(transaction.amount)))),
                bank_transaction_id=transaction.id,
                notes="Linked manually from admin invoice detail.",
            )
        )

    db.flush()
    _recalculate_conciliation(db, conciliation=conciliation, item_details=item_details)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CreditCardInvoiceConciliationError("Nao foi possivel salvar a conciliacao da fatura.") from exc
    db.refresh(conciliation)
    return conciliation


def unlink_credit_card_invoice_bank_payment(
    db: Session,
    *,
    invoice_id: int,
    conciliation_item_id: int,
) -> CreditCardInvoiceConciliation:
    row = _load_invoice_row(db, invoice_id=invoice_id)
    if row is None:
        raise CreditCardInvoiceConciliationError("Fatura nao encontrada.")

    invoice, _, _ = row
    item_details = _load_invoice_item_details(db, invoice_id=invoice.id)
    conciliation = _get_or_create_conciliation(db, invoice=invoice, item_details=item_details)
    conciliation_item = db.scalar(
        select(CreditCardInvoiceConciliationItem)
        .where(
            CreditCardInvoiceConciliationItem.id == conciliation_item_id,
            CreditCardInvoiceConciliationItem.conciliation_id == conciliation.id,
            CreditCardInvoiceConciliationItem.item_type == "bank_payment",
        )
    )
    if conciliation_item is None:
        raise CreditCardInvoiceConciliationError("Vinculo de pagamento nao encontrado.")

    db.delete(conciliation_item)
    db.flush()
    _recalculate_conciliation(db, conciliation=conciliation, item_details=item_details)
    db.commit()
    db.refresh(conciliation)
    return conciliation


def create_credit_card(
    db: Session,
    *,
    issuer: str,
    card_label: str,
    card_final: str,
    brand: str | None,
    is_active: bool = True,
) -> CreditCard:
    normalized_issuer = issuer.strip().lower()
    normalized_final = "".join(ch for ch in card_final if ch.isdigit())
    if len(normalized_final) != 4:
        raise CreditCardBillError("Card final must have 4 digits")

    card = CreditCard(
        issuer=normalized_issuer,
        card_label=card_label.strip(),
        card_final=normalized_final,
        brand=brand.strip() if brand and brand.strip() else None,
        is_active=is_active,
    )
    db.add(card)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CreditCardBillConflictError("Ja existe um cartao com esse emissor e final.") from exc
    db.refresh(card)
    return card


def _validate_upload_input(upload_input: CreditCardBillUploadInput) -> None:
    if upload_input.billing_month < 1 or upload_input.billing_month > 12:
        raise CreditCardBillError("Billing month must be between 1 and 12")
    if upload_input.billing_year < 2000 or upload_input.billing_year > 2100:
        raise CreditCardBillError("Billing year is out of allowed range")


def _build_row_hash(
    *,
    card_id: int,
    billing_year: int,
    billing_month: int,
    purchase_date: date,
    description_raw: str,
    amount_brl: Decimal,
    installment_current: int | None,
    installment_total: int | None,
) -> str:
    return canonical_hash(
        "|".join(
            [
                str(card_id),
                str(billing_year),
                str(billing_month),
                purchase_date.isoformat(),
                description_raw.strip(),
                f"{amount_brl:.2f}",
                str(installment_current or ""),
                str(installment_total or ""),
            ]
        )
    )


def import_credit_card_bill(
    db: Session,
    *,
    file_name: str,
    raw_content: bytes,
    upload_input: CreditCardBillUploadInput,
) -> dict:
    if not file_name:
        raise CreditCardBillError("File name is required")
    if not raw_content:
        raise CreditCardBillError("Empty file")

    _validate_upload_input(upload_input)

    card = db.get(CreditCard, upload_input.card_id)
    if card is None:
        raise CreditCardBillError("Credit card not found")

    current_file_hash = file_hash(raw_content)
    duplicate_invoice = db.scalar(
        select(CreditCardInvoice).where(CreditCardInvoice.source_file_hash == current_file_hash)
    )
    if duplicate_invoice is not None:
        raise CreditCardBillDuplicateFileError("Arquivo duplicado: esta fatura ja foi enviada.")

    conflicting_invoice = db.scalar(
        select(CreditCardInvoice).where(
            CreditCardInvoice.card_id == upload_input.card_id,
            CreditCardInvoice.billing_year == upload_input.billing_year,
            CreditCardInvoice.billing_month == upload_input.billing_month,
        )
    )
    if conflicting_invoice is not None:
        raise CreditCardBillConflictError("Conflito: ja existe uma fatura para este cartao e competencia.")

    items = parse_itau_credit_card_csv(raw_content)
    seen_row_hashes: set[str] = set()

    try:
        source_file = SourceFile(
            source_type="credit_card_bill",
            file_name=file_name,
            file_path=f"upload://{file_name}",
            reference_id=None,
            file_hash=current_file_hash,
            status="processed",
        )
        db.add(source_file)
        db.flush()

        invoice = CreditCardInvoice(
            source_file_id=source_file.id,
            card_id=card.id,
            issuer=card.issuer,
            card_final=card.card_final,
            billing_year=upload_input.billing_year,
            billing_month=upload_input.billing_month,
            due_date=upload_input.due_date,
            closing_date=upload_input.closing_date,
            total_amount_brl=upload_input.total_amount_brl,
            source_file_name=file_name,
            source_file_hash=current_file_hash,
            notes=upload_input.notes.strip() if upload_input.notes and upload_input.notes.strip() else None,
            import_status="imported",
        )
        db.add(invoice)
        db.flush()

        for item in items:
            row_hash = _build_row_hash(
                card_id=card.id,
                billing_year=upload_input.billing_year,
                billing_month=upload_input.billing_month,
                purchase_date=item["purchase_date"],
                description_raw=item["description_raw"],
                amount_brl=item["amount_brl"],
                installment_current=item["installment_current"],
                installment_total=item["installment_total"],
            )
            if row_hash in seen_row_hashes:
                raise CreditCardBillError("Estrutura invalida: linha duplicada dentro da fatura.")
            seen_row_hashes.add(row_hash)
            db.add(
                CreditCardInvoiceItem(
                    invoice_id=invoice.id,
                    purchase_date=item["purchase_date"],
                    description_raw=item["description_raw"],
                    description_normalized=item["description_normalized"],
                    amount_brl=item["amount_brl"],
                    installment_current=item["installment_current"],
                    installment_total=item["installment_total"],
                    is_installment=item["is_installment"],
                    derived_note=item["derived_note"],
                    external_row_hash=row_hash,
                )
            )

        db.commit()
        return {
            "status": "processed",
            "message": f"Fatura importada com {len(items)} lancamentos.",
            "invoice_id": invoice.id,
            "imported_items": len(items),
        }
    except IntegrityError as exc:
        db.rollback()
        raise CreditCardBillConflictError("Conflito ao salvar a fatura ou seus lancamentos.") from exc
    except Exception:
        db.rollback()
        raise


