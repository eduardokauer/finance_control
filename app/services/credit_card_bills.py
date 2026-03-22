from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.parsers.credit_card_bill_parser import parse_itau_credit_card_csv
from app.repositories.models import CreditCard, CreditCardInvoice, CreditCardInvoiceItem, SourceFile
from app.utils.hashing import canonical_hash, file_hash


class CreditCardBillError(Exception):
    status_code = 422


class CreditCardBillDuplicateFileError(CreditCardBillError):
    status_code = 409


class CreditCardBillConflictError(CreditCardBillError):
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


@dataclass
class CreditCardInvoiceListEntry:
    invoice: CreditCardInvoice
    card: CreditCard
    item_count: int


@dataclass
class CreditCardInvoiceDetail:
    invoice: CreditCardInvoice
    card: CreditCard
    source_file: SourceFile | None
    items: list[CreditCardInvoiceItem]
    item_count: int
    items_total_brl: Decimal


def list_credit_cards(db: Session, *, active_only: bool = False) -> list[CreditCard]:
    query = select(CreditCard)
    if active_only:
        query = query.where(CreditCard.is_active.is_(True))
    return db.scalars(query.order_by(CreditCard.is_active.desc(), CreditCard.card_label.asc(), CreditCard.id.asc())).all()


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


def get_credit_card_invoice_detail(db: Session, *, invoice_id: int) -> CreditCardInvoiceDetail | None:
    row = db.execute(
        select(CreditCardInvoice, CreditCard, SourceFile)
        .join(CreditCard, CreditCard.id == CreditCardInvoice.card_id)
        .outerjoin(SourceFile, SourceFile.id == CreditCardInvoice.source_file_id)
        .where(CreditCardInvoice.id == invoice_id)
    ).one_or_none()
    if row is None:
        return None

    invoice, card, source_file = row
    items = db.scalars(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id)
        .order_by(CreditCardInvoiceItem.purchase_date.asc(), CreditCardInvoiceItem.id.asc())
    ).all()
    items_total_brl = sum((item.amount_brl for item in items), Decimal("0.00"))
    return CreditCardInvoiceDetail(
        invoice=invoice,
        card=card,
        source_file=source_file,
        items=items,
        item_count=len(items),
        items_total_brl=items_total_brl,
    )


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
        raise CreditCardBillConflictError("Já existe um cartão com esse emissor e final.") from exc
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
        raise CreditCardBillDuplicateFileError("Arquivo duplicado: esta fatura já foi enviada.")

    conflicting_invoice = db.scalar(
        select(CreditCardInvoice).where(
            CreditCardInvoice.card_id == upload_input.card_id,
            CreditCardInvoice.billing_year == upload_input.billing_year,
            CreditCardInvoice.billing_month == upload_input.billing_month,
        )
    )
    if conflicting_invoice is not None:
        raise CreditCardBillConflictError("Conflito: já existe uma fatura para este cartão e competência.")

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
                raise CreditCardBillError("Estrutura inválida: linha duplicada dentro da fatura.")
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
            "message": f"Fatura importada com {len(items)} lançamentos.",
            "invoice_id": invoice.id,
            "imported_items": len(items),
        }
    except IntegrityError as exc:
        db.rollback()
        raise CreditCardBillConflictError("Conflito ao salvar a fatura ou seus lançamentos.") from exc
    except Exception:
        db.rollback()
        raise
