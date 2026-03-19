from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
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
    total_amount_brl: float
    closing_date: date | None = None
    notes: str | None = None


def list_credit_cards(db: Session, *, active_only: bool = False) -> list[CreditCard]:
    query = select(CreditCard)
    if active_only:
        query = query.where(CreditCard.is_active.is_(True))
    return db.scalars(query.order_by(CreditCard.is_active.desc(), CreditCard.card_label.asc(), CreditCard.id.asc())).all()


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
    amount_brl: float,
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
    upload_input: CreditCardBillUploadInput | None = None,
    payload: CreditCardBillUploadInput | None = None,
) -> dict:
    if not file_name:
        raise CreditCardBillError("File name is required")
    if not raw_content:
        raise CreditCardBillError("Empty file")

    resolved_input = upload_input or payload
    if resolved_input is None:
        raise CreditCardBillError("Upload input is required")

    _validate_upload_input(resolved_input)

    card = db.get(CreditCard, resolved_input.card_id)
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
            CreditCardInvoice.card_id == resolved_input.card_id,
            CreditCardInvoice.billing_year == resolved_input.billing_year,
            CreditCardInvoice.billing_month == resolved_input.billing_month,
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
            billing_year=resolved_input.billing_year,
            billing_month=resolved_input.billing_month,
            due_date=resolved_input.due_date,
            closing_date=resolved_input.closing_date,
            total_amount_brl=resolved_input.total_amount_brl,
            source_file_name=file_name,
            source_file_hash=current_file_hash,
            notes=resolved_input.notes.strip() if resolved_input.notes and resolved_input.notes.strip() else None,
            import_status="imported",
        )
        db.add(invoice)
        db.flush()

        for item in items:
            row_hash = _build_row_hash(
                card_id=card.id,
                billing_year=resolved_input.billing_year,
                billing_month=resolved_input.billing_month,
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
