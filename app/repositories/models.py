from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(40), default="processed", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RawTransaction(Base):
    __tablename__ = "raw_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_date: Mapped[str] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    transaction_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="expense")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CategorizationRule(Base):
    __tablename__ = "categorization_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    category_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="flow")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("source_type", "external_id", name="uq_transactions_external"),
        UniqueConstraint("canonical_hash", name="uq_transactions_canonical_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    account_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_date: Mapped[str] = mapped_column(Date, nullable=False)
    competence_month: Mapped[str] = mapped_column(String(7), nullable=False)
    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    description_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    transaction_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    categorization_method: Mapped[str] = mapped_column(String(40), nullable=False)
    categorization_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    applied_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    categorization_rule_id: Mapped[int | None] = mapped_column(ForeignKey("categorization_rules.id"), nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_updated_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_card_bill_payment: Mapped[bool] = mapped_column(Boolean, default=False)
    is_adjustment: Mapped[bool] = mapped_column(Boolean, default=False)
    is_reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    should_count_in_spending: Mapped[bool] = mapped_column(Boolean, default=True)


class Reconciliation(Base):
    __tablename__ = "reconciliations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReconciliationItem(Base):
    __tablename__ = "reconciliation_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("reconciliations.id"), nullable=False)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_start: Mapped[str] = mapped_column(Date, nullable=False)
    period_end: Mapped[str] = mapped_column(Date, nullable=False)
    trigger_source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    html_output: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransactionAuditLog(Base):
    __tablename__ = "transaction_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    origin: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    new_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    previous_transaction_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_transaction_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    applied_rule_id: Mapped[int | None] = mapped_column(ForeignKey("categorization_rules.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditCard(Base):
    __tablename__ = "credit_cards"
    __table_args__ = (
        UniqueConstraint("issuer", "card_final", name="uq_credit_cards_issuer_final"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issuer: Mapped[str] = mapped_column(String(40), nullable=False)
    card_label: Mapped[str] = mapped_column(String(120), nullable=False)
    card_final: Mapped[str] = mapped_column(String(4), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CreditCardInvoice(Base):
    __tablename__ = "credit_card_invoices"
    __table_args__ = (
        UniqueConstraint("card_id", "billing_year", "billing_month", name="uq_credit_card_invoices_card_period"),
        UniqueConstraint("source_file_hash", name="uq_credit_card_invoices_file_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), nullable=False)
    card_id: Mapped[int] = mapped_column(ForeignKey("credit_cards.id"), nullable=False)
    issuer: Mapped[str] = mapped_column(String(40), nullable=False)
    card_final: Mapped[str] = mapped_column(String(4), nullable=False)
    billing_year: Mapped[int] = mapped_column(Integer, nullable=False)
    billing_month: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[str] = mapped_column(Date, nullable=False)
    closing_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    total_amount_brl: Mapped[float] = mapped_column(Float, nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_status: Mapped[str] = mapped_column(String(30), default="imported", nullable=False)
    imported_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditCardInvoiceItem(Base):
    __tablename__ = "credit_card_invoice_items"
    __table_args__ = (
        UniqueConstraint("invoice_id", "external_row_hash", name="uq_credit_card_invoice_items_row_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("credit_card_invoices.id"), nullable=False)
    purchase_date: Mapped[str] = mapped_column(Date, nullable=False)
    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    description_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_brl: Mapped[float] = mapped_column(Float, nullable=False)
    installment_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_installment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    derived_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
