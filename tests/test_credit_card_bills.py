from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.repositories.models import CategorizationRule, Category, CreditCard, CreditCardInvoice, CreditCardInvoiceItem, SourceFile
from app.services.credit_card_bills import (
    CreditCardBillUploadInput,
    CreditCardInvoiceCategoryEditError,
    apply_manual_credit_card_invoice_item_category_change,
    apply_manual_credit_card_invoice_item_category_rule_application,
    classify_credit_card_invoice_item,
    create_credit_card,
    ensure_credit_card_invoice_conciliation,
    get_credit_card_invoice_detail,
    import_credit_card_bill,
    preview_manual_credit_card_invoice_item_category_change,
    preview_manual_credit_card_invoice_item_category_rule_application,
    recategorize_credit_card_invoice_items,
)


def _create_card(db_session) -> CreditCard:
    return create_credit_card(
        db_session,
        issuer="itau",
        card_label="Itaú Visa final 1234",
        card_final="1234",
        brand="Visa",
        is_active=True,
    )


def _create_invoice_with_items(db_session, *, descriptions_and_amounts: list[tuple[str, str]], total_amount_brl: str = "0.00") -> CreditCardInvoice:
    card = _create_card(db_session)
    source_file = SourceFile(
        source_type="credit_card_bill",
        file_name="invoice-test.csv",
        file_path="upload://invoice-test.csv",
        file_hash=f"invoice-test-{len(descriptions_and_amounts)}",
        status="processed",
    )
    db_session.add(source_file)
    db_session.flush()

    invoice = CreditCardInvoice(
        source_file_id=source_file.id,
        card_id=card.id,
        issuer=card.issuer,
        card_final=card.card_final,
        billing_year=2026,
        billing_month=2,
        due_date=date(2026, 2, 20),
        closing_date=date(2026, 2, 7),
        total_amount_brl=Decimal(total_amount_brl),
        source_file_name=source_file.file_name,
        source_file_hash=f"invoice-hash-{len(descriptions_and_amounts)}",
        notes="invoice test",
        import_status="imported",
    )
    db_session.add(invoice)
    db_session.flush()

    for index, (description_raw, amount_brl) in enumerate(descriptions_and_amounts, start=1):
        db_session.add(
            CreditCardInvoiceItem(
                invoice_id=invoice.id,
                purchase_date=date(2026, 2, min(index, 28)),
                description_raw=description_raw,
                description_normalized=description_raw.lower(),
                amount_brl=Decimal(amount_brl),
                installment_current=None,
                installment_total=None,
                is_installment=False,
                derived_note=None,
                external_row_hash=f"row-hash-{invoice.id}-{index}",
            )
        )

    db_session.commit()
    db_session.refresh(invoice)
    return invoice


def _upload_invoice(client, auth_headers, card_id: int, csv_file, **overrides):
    data = {
        "billing_month": str(overrides.get("billing_month", 3)),
        "billing_year": str(overrides.get("billing_year", 2026)),
        "due_date": overrides.get("due_date", "2026-03-20"),
        "card_id": str(card_id),
        "total_amount_brl": overrides.get("total_amount_brl", "130.45"),
    }
    if "closing_date" in overrides:
        data["closing_date"] = overrides["closing_date"]
    if "notes" in overrides:
        data["notes"] = overrides["notes"]
    with csv_file.open("rb") as handle:
        return client.post(
            "/ingest/credit-card-bill",
            headers=auth_headers,
            data=data,
            files={"file": (csv_file.name, handle, "text/csv")},
        )        


def _seed_categories(db_session):
    for name, kind in [
        ("Não Categorizado", "expense"),
        ("Supermercado", "expense"),
        ("Educação", "expense"),
        ("Ajustes e Estornos", "expense"),
        ("Transferências", "transfer"),
        ("Outras Receitas", "income"),
    ]:
        db_session.add(Category(name=name, transaction_kind=kind, is_active=True))
    db_session.commit()


def test_credit_card_creation_persists_basic_entity(db_session):
    card = _create_card(db_session)

    persisted = db_session.get(CreditCard, card.id)
    assert persisted is not None
    assert persisted.issuer == "itau"
    assert persisted.card_final == "1234"


def test_credit_card_invoice_upload_persists_invoice_and_items(
    client,
    db_session,
    auth_headers,
    sample_credit_card_csv_file,
):
    card = _create_card(db_session)

    response = _upload_invoice(
        client,
        auth_headers,
        card.id,
        sample_credit_card_csv_file,
        notes="Fatura março",
        closing_date="2026-03-12",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["invoice_id"] is not None
    assert body["imported_items"] == 2
    assert "analysis_run_id" not in body
    assert "period_start" not in body
    assert "period_end" not in body
    assert "source_file_id" not in body

    invoice = db_session.scalar(select(CreditCardInvoice))
    assert invoice is not None
    assert invoice.card_id == card.id
    assert invoice.billing_year == 2026
    assert invoice.billing_month == 3
    assert invoice.due_date == date(2026, 3, 20)
    assert invoice.closing_date == date(2026, 3, 12)
    assert invoice.total_amount_brl == Decimal("130.45")
    assert invoice.notes == "Fatura março"

    items = db_session.scalars(select(CreditCardInvoiceItem).order_by(CreditCardInvoiceItem.id)).all()
    assert len(items) == 2
    assert items[0].purchase_date == date(2026, 3, 5)
    assert items[0].amount_brl == Decimal("-120.45")
    assert items[0].is_installment is True
    assert items[0].installment_current == 6
    assert items[0].installment_total == 8
    assert items[0].derived_note == "Parcela 6/8"
    assert items[1].amount_brl == Decimal("-10.00")


def test_credit_card_invoice_upload_blocks_duplicate_file(
    client,
    db_session,
    auth_headers,
    sample_credit_card_csv_file,
):
    card = _create_card(db_session)

    first = _upload_invoice(client, auth_headers, card.id, sample_credit_card_csv_file)
    second = _upload_invoice(client, auth_headers, card.id, sample_credit_card_csv_file, billing_month=4)

    assert first.status_code == 200
    assert second.status_code == 409
    assert "Arquivo duplicado" in second.json()["detail"]


def test_credit_card_invoice_upload_blocks_same_card_and_competence_conflict(
    client,
    db_session,
    auth_headers,
    sample_credit_card_csv_file,
    tmp_path,
):
    card = _create_card(db_session)
    other_file = tmp_path / "fatura_outro_hash.csv"
    other_file.write_text("data;lançamento;valor\n07/03/2026;POSTO SHELL;-90,00\n", encoding="utf-8")

    first = _upload_invoice(client, auth_headers, card.id, sample_credit_card_csv_file)
    second = _upload_invoice(client, auth_headers, card.id, other_file)

    assert first.status_code == 200
    assert second.status_code == 409
    assert "Conflito" in second.json()["detail"]


def test_credit_card_invoice_upload_is_transactional_on_invalid_structure(
    client,
    db_session,
    auth_headers,
    invalid_credit_card_csv_file,
):
    card = _create_card(db_session)

    response = _upload_invoice(client, auth_headers, card.id, invalid_credit_card_csv_file)

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(CreditCardInvoice)) == 0
    assert db_session.scalar(select(func.count()).select_from(CreditCardInvoiceItem)) == 0


def test_credit_card_invoice_upload_preserves_negative_values_and_original_purchase_date(
    client,
    db_session,
    auth_headers,
    sample_credit_card_csv_file,
):
    card = _create_card(db_session)

    response = _upload_invoice(client, auth_headers, card.id, sample_credit_card_csv_file)

    assert response.status_code == 200
    item = db_session.scalar(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.description_raw == "ESTORNO LOJA")
    )
    assert item is not None
    assert item.amount_brl == Decimal("-10.00")
    assert item.purchase_date == date(2026, 3, 6)


def test_credit_card_invoice_upload_rejects_empty_file(
    client,
    db_session,
    auth_headers,
    tmp_path,
):
    card = _create_card(db_session)
    empty_file = tmp_path / "fatura_vazia.csv"
    empty_file.write_bytes(b"")

    response = _upload_invoice(client, auth_headers, card.id, empty_file)

    assert response.status_code == 422
    assert response.json()["detail"] == "Empty file"


def test_credit_card_invoice_upload_accepts_current_real_csv_layout(
    client,
    db_session,
    auth_headers,
    real_layout_credit_card_csv_file,
):
    card = _create_card(db_session)

    response = _upload_invoice(
        client,
        auth_headers,
        card.id,
        real_layout_credit_card_csv_file,
        total_amount_brl="640.78",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["imported_items"] == 2

    items = db_session.scalars(select(CreditCardInvoiceItem).order_by(CreditCardInvoiceItem.id)).all()
    assert len(items) == 2
    assert items[0].purchase_date == date(2026, 2, 27)
    assert items[0].amount_brl == Decimal("5.50")
    assert items[1].purchase_date == date(2026, 2, 22)
    assert items[1].amount_brl == Decimal("-646.28")


def test_credit_card_invoice_upload_allows_duplicate_rows_within_same_file(
    client,
    db_session,
    auth_headers,
    tmp_path,
):
    card = _create_card(db_session)
    duplicate_rows_file = tmp_path / "fatura_com_linhas_iguais.csv"
    duplicate_rows_file.write_text(
        "data;lançamento;valor\n"
        "11/08/2025;ZONA AZUL BARUERI;2,00\n"
        "11/08/2025;ZONA AZUL BARUERI;2,00\n",
        encoding="utf-8",
    )

    response = _upload_invoice(
        client,
        auth_headers,
        card.id,
        duplicate_rows_file,
        billing_month=9,
        billing_year=2025,
        due_date="2025-09-07",
        total_amount_brl="4.00",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["imported_items"] == 2

    items = db_session.scalars(select(CreditCardInvoiceItem).order_by(CreditCardInvoiceItem.id)).all()
    assert len(items) == 2
    assert items[0].purchase_date == date(2025, 8, 11)
    assert items[1].purchase_date == date(2025, 8, 11)
    assert items[0].description_raw == "ZONA AZUL BARUERI"
    assert items[1].description_raw == "ZONA AZUL BARUERI"
    assert items[0].amount_brl == Decimal("2.00")
    assert items[1].amount_brl == Decimal("2.00")
    assert items[0].external_row_hash != items[1].external_row_hash


def test_credit_card_invoice_upload_accepts_real_fixture_file(
    client,
    db_session,
    auth_headers,
    real_credit_card_bill_file,
):
    card = _create_card(db_session)

    response = _upload_invoice(
        client,
        auth_headers,
        card.id,
        real_credit_card_bill_file,
        billing_month=3,
        billing_year=2026,
        due_date="2026-03-20",
        closing_date="2026-03-07",
        total_amount_brl="0.00",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["imported_items"] == 69

    items = db_session.scalars(select(CreditCardInvoiceItem).order_by(CreditCardInvoiceItem.id)).all()
    assert len(items) == 69
    assert items[0].purchase_date == date(2026, 2, 27)
    assert items[0].description_raw == "KALUNGA-ALPH-CT LE"
    assert items[0].amount_brl == Decimal("5.50")
    assert items[-1].purchase_date == date(2025, 7, 15)
    assert items[-1].description_raw == "MP *SAMSUNG       08/18"
    assert items[-1].amount_brl == Decimal("214.23")


def test_credit_card_invoice_upload_categorizes_charge_and_keeps_technical_items_without_category(
    client,
    db_session,
    auth_headers,
    tmp_path,
):
    _seed_categories(db_session)
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="supermercado extra",
            category_name="Supermercado",
            kind_mode="flow",
            source_scope="credit_card_invoice_item",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()
    card = _create_card(db_session)
    categorized_file = tmp_path / "fatura_categorizada.csv"
    categorized_file.write_text(
        "data;lançamento;valor\n"
        "05/03/2026;SUPERMERCADO EXTRA;120,45\n"
        "06/03/2026;DESCONTO NA FATURA - PO;-10,00\n"
        "07/03/2026;PAGAMENTO EFETUADO;-110,45\n",
        encoding="utf-8",
    )

    response = _upload_invoice(
        client,
        auth_headers,
        card.id,
        categorized_file,
        total_amount_brl="110.45",
    )

    assert response.status_code == 200
    items = db_session.scalars(select(CreditCardInvoiceItem).order_by(CreditCardInvoiceItem.id.asc())).all()
    assert len(items) == 3
    assert items[0].category == "Supermercado"
    assert items[0].categorization_method == "rule"
    assert items[0].applied_rule == "supermercado extra"
    assert items[0].categorization_rule_id is not None
    assert items[1].category is None
    assert items[1].categorization_method is None
    assert items[2].category is None
    assert items[2].categorization_method is None
    assert db_session.scalar(select(Category).where(Category.name == items[0].category)) is not None


def test_credit_card_invoice_charge_fallback_without_official_category_uses_official_uncategorized(
    client,
    db_session,
    auth_headers,
    tmp_path,
    monkeypatch,
):
    _seed_categories(db_session)
    card = _create_card(db_session)
    categorized_file = tmp_path / "fatura_categoria_inexistente.csv"
    categorized_file.write_text(
        "data;lançamento;valor\n"
        "05/03/2026;ASSINATURA DESCONHECIDA;120,45\n",
        encoding="utf-8",
    )

    def fake_classification(*_args, **_kwargs):
        return {
            "category": "Categoria Fantasma",
            "method": "fallback",
            "confidence": 0.3,
            "rule": None,
            "rule_id": None,
            "normalized_description": "assinatura desconhecida",
        }

    monkeypatch.setattr("app.services.credit_card_bills.classify_credit_card_invoice_charge", fake_classification)

    response = _upload_invoice(
        client,
        auth_headers,
        card.id,
        categorized_file,
        total_amount_brl="120.45",
    )

    assert response.status_code == 200
    item = db_session.scalar(select(CreditCardInvoiceItem))
    assert item is not None
    assert item.category == "Não Categorizado"
    assert item.categorization_method == "fallback"
    assert db_session.scalar(select(Category).where(Category.name == item.category)) is not None
    assert db_session.scalar(select(Category).where(Category.name == "Categoria Fantasma")) is None


def test_credit_card_invoice_item_classifies_payment_and_credit(db_session):
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[
            ("PAGAMENTO EFETUADO", "-850.00"),
            ("DESCONTO NA FATURA - PO", "-646.28"),
            ("COMPRA MERCADO", "120.00"),
        ],
        total_amount_brl="-526.28",
    )

    items = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
    ).all()

    assert classify_credit_card_invoice_item(items[0]) == "payment"
    assert classify_credit_card_invoice_item(items[1]) == "credit"
    assert classify_credit_card_invoice_item(items[2]) == "charge"


def test_credit_card_invoice_item_recategorization_reapplies_only_charges_and_respects_source_scope(db_session):
    _seed_categories(db_session)
    db_session.add(Category(name="Moradia", transaction_kind="expense", is_active=True))
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="curso plataforma",
            category_name="Moradia",
            kind_mode="flow",
            source_scope="bank_statement",
            priority=0,
            is_active=True,
        )
    )
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="curso plataforma",
            category_name="Educação",
            kind_mode="flow",
            source_scope="credit_card_invoice_item",
            priority=1,
            is_active=True,
        )
    )
    db_session.commit()

    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[
            ("CURSO PLATAFORMA ONLINE", "120.00"),
            ("DESCONTO NA FATURA - PO", "-10.00"),
            ("PAGAMENTO EFETUADO", "-110.00"),
        ],
        total_amount_brl="0.00",
    )
    items = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    items[0].category = "Não Categorizado"
    items[0].categorization_method = "fallback"
    items[0].categorization_confidence = 0.3
    items[1].category = "Supermercado"
    items[1].categorization_method = "legacy"
    items[1].categorization_confidence = 1.0
    items[1].applied_rule = "legacy"
    items[2].category = "Supermercado"
    items[2].categorization_method = "legacy"
    items[2].categorization_confidence = 1.0
    items[2].applied_rule = "legacy"
    db_session.commit()

    result = recategorize_credit_card_invoice_items(db_session, invoice_id=invoice.id)

    refreshed_items = db_session.scalars(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id).order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    assert result == {"checked_count": 3, "updated_count": 3}
    assert refreshed_items[0].category == "Educação"
    assert refreshed_items[0].categorization_method == "rule"
    assert refreshed_items[0].categorization_rule_id is not None
    assert refreshed_items[1].category is None
    assert refreshed_items[1].categorization_method is None
    assert refreshed_items[1].categorization_rule_id is None
    assert refreshed_items[2].category is None
    assert refreshed_items[2].categorization_method is None
    assert refreshed_items[2].categorization_rule_id is None


def test_manual_credit_card_invoice_item_category_preview_and_apply_persists_manual_choice(db_session):
    _seed_categories(db_session)
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[("SUPERMERCADO TESTE", "120.00")],
        total_amount_brl="120.00",
    )
    item = db_session.scalar(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id)
    )
    assert item is not None
    item.category = "Supermercado"
    item.categorization_method = "rule"
    item.categorization_confidence = 0.9
    conciliation = ensure_credit_card_invoice_conciliation(db_session, invoice_id=invoice.id)
    assert conciliation is not None
    conciliation.status = "conciliated"
    db_session.commit()

    preview = preview_manual_credit_card_invoice_item_category_change(
        db_session,
        invoice_id=invoice.id,
        item_id=item.id,
        category_name="Educação",
    )

    assert preview.current_category == "Supermercado"
    assert preview.selected_category == "Educação"
    assert preview.is_visible_in_analysis is True
    assert "Supermercado" in preview.impact_summary
    assert "Educação" in preview.impact_summary

    updated = apply_manual_credit_card_invoice_item_category_change(
        db_session,
        invoice_id=invoice.id,
        item_id=item.id,
        category_name="Educação",
    )

    assert updated.category == "Educação"
    assert updated.categorization_method == "manual"
    assert updated.categorization_confidence == 1.0
    assert updated.applied_rule is None
    assert updated.categorization_rule_id is None


def test_manual_credit_card_invoice_item_category_apply_to_base_creates_rule_reapplies_existing_items_and_future_imports(db_session):
    _seed_categories(db_session)
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[
            ("SUPERMERCADO TESTE", "120.00"),
            ("SUPERMERCADO TESTE", "45.00"),
            ("CURSO ONLINE", "30.00"),
        ],
        total_amount_brl="195.00",
    )
    items = db_session.scalars(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id)
        .order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    target_item = items[0]

    preview = preview_manual_credit_card_invoice_item_category_rule_application(
        db_session,
        invoice_id=invoice.id,
        item_id=target_item.id,
        category_name="Supermercado",
        rule_pattern="supermercado teste",
        rule_type="exact_normalized",
    )

    assert preview.rule_id_to_update is None
    assert preview.affected_count == 2
    assert preview.affected_total_brl == Decimal("165.00")
    assert "importações futuras" in preview.future_imports_note
    assert preview.category_distribution[0].category_name == "Não Categorizado"
    assert {item.description_raw for item in preview.impacted_items} == {"SUPERMERCADO TESTE"}

    result = apply_manual_credit_card_invoice_item_category_rule_application(
        db_session,
        invoice_id=invoice.id,
        item_id=target_item.id,
        category_name="Supermercado",
        rule_pattern="supermercado teste",
        rule_type="exact_normalized",
    )

    assert result.rule.category_name == "Supermercado"
    assert result.rule.rule_type == "exact_normalized"
    assert result.rule.source_scope == "credit_card_invoice_item"
    assert result.rule.is_active is True
    assert result.reapply_result["checked_count"] == 2

    refreshed_items = db_session.scalars(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id)
        .order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    assert refreshed_items[0].category == "Supermercado"
    assert refreshed_items[0].categorization_method == "rule"
    assert refreshed_items[0].categorization_rule_id == result.rule.id
    assert refreshed_items[1].category == "Supermercado"
    assert refreshed_items[1].categorization_method == "rule"
    assert refreshed_items[1].categorization_rule_id == result.rule.id
    assert refreshed_items[2].category in (None, "Não Categorizado")

    imported = import_credit_card_bill(
        db_session,
        file_name="invoice-future.csv",
        raw_content="data;lançamento;valor\n05/05/2026;SUPERMERCADO TESTE;80,00\n".encode("utf-8"),
        upload_input=CreditCardBillUploadInput(
            card_id=invoice.card_id,
            billing_year=2026,
            billing_month=5,
            due_date=date(2026, 5, 20),
            closing_date=date(2026, 5, 12),
            total_amount_brl=Decimal("80.00"),
            notes="future import",
        ),
    )

    imported_item = db_session.scalar(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == imported["invoice_id"])
    )
    assert imported_item is not None
    assert imported_item.category == "Supermercado"
    assert imported_item.categorization_method == "rule"
    assert imported_item.categorization_rule_id == result.rule.id


def test_manual_credit_card_invoice_item_category_apply_to_base_updates_existing_invoice_rule(db_session):
    _seed_categories(db_session)
    existing_rule = CategorizationRule(
        rule_type="exact_normalized",
        pattern="supermercado teste",
        category_name="Outros",
        kind_mode="flow",
        source_scope="credit_card_invoice_item",
        priority=0,
        is_active=True,
    )
    db_session.add(existing_rule)
    db_session.commit()

    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[
            ("SUPERMERCADO TESTE", "120.00"),
            ("SUPERMERCADO TESTE", "45.00"),
        ],
        total_amount_brl="165.00",
    )
    items = db_session.scalars(
        select(CreditCardInvoiceItem)
        .where(CreditCardInvoiceItem.invoice_id == invoice.id)
        .order_by(CreditCardInvoiceItem.id.asc())
    ).all()
    for item in items:
        item.category = "Outros"
        item.categorization_method = "rule"
        item.categorization_confidence = 1.0
        item.applied_rule = existing_rule.pattern
        item.categorization_rule_id = existing_rule.id
    db_session.commit()

    preview = preview_manual_credit_card_invoice_item_category_rule_application(
        db_session,
        invoice_id=invoice.id,
        item_id=items[0].id,
        category_name="Supermercado",
        rule_pattern="supermercado teste",
        rule_type="exact_normalized",
    )

    assert preview.rule_id_to_update == existing_rule.id
    assert "será atualizada" in preview.rule_action_label

    result = apply_manual_credit_card_invoice_item_category_rule_application(
        db_session,
        invoice_id=invoice.id,
        item_id=items[0].id,
        category_name="Supermercado",
        rule_pattern="supermercado teste",
        rule_type="exact_normalized",
    )

    assert result.rule.id == existing_rule.id
    assert result.rule.category_name == "Supermercado"
    assert result.reapply_result["updated_count"] == 2


def test_manual_credit_card_invoice_item_category_apply_to_base_blocks_non_charge_items(db_session):
    _seed_categories(db_session)
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[("PAGAMENTO EFETUADO", "-850.00")],
        total_amount_brl="-850.00",
    )
    item = db_session.scalar(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id)
    )
    assert item is not None

    with pytest.raises(CreditCardInvoiceCategoryEditError):
        preview_manual_credit_card_invoice_item_category_rule_application(
            db_session,
            invoice_id=invoice.id,
            item_id=item.id,
            category_name="Educação",
            rule_pattern="pagamento efetuado",
            rule_type="exact_normalized",
        )


def test_manual_credit_card_invoice_item_category_apply_to_base_rejects_invalid_category(db_session):
    _seed_categories(db_session)
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[("CURSO ONLINE", "120.00")],
        total_amount_brl="120.00",
    )
    item = db_session.scalar(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id)
    )
    assert item is not None

    with pytest.raises(CreditCardInvoiceCategoryEditError):
        preview_manual_credit_card_invoice_item_category_rule_application(
            db_session,
            invoice_id=invoice.id,
            item_id=item.id,
            category_name="Categoria Fantasma",
            rule_pattern="curso online",
            rule_type="exact_normalized",
        )


def test_manual_credit_card_invoice_item_category_blocks_non_charge_items(db_session):
    _seed_categories(db_session)
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[("PAGAMENTO EFETUADO", "-850.00")],
        total_amount_brl="-850.00",
    )
    item = db_session.scalar(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id)
    )
    assert item is not None

    with pytest.raises(CreditCardInvoiceCategoryEditError):
        preview_manual_credit_card_invoice_item_category_change(
            db_session,
            invoice_id=invoice.id,
            item_id=item.id,
            category_name="Educação",
        )


def test_manual_credit_card_invoice_item_category_rejects_invalid_or_unknown_category(db_session):
    _seed_categories(db_session)
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[("CURSO ONLINE", "120.00")],
        total_amount_brl="120.00",
    )
    item = db_session.scalar(
        select(CreditCardInvoiceItem).where(CreditCardInvoiceItem.invoice_id == invoice.id)
    )
    assert item is not None

    with pytest.raises(CreditCardInvoiceCategoryEditError):
        preview_manual_credit_card_invoice_item_category_change(
            db_session,
            invoice_id=invoice.id,
            item_id=item.id,
            category_name="Categoria Fantasma",
        )


def test_credit_card_invoice_detail_summary_excludes_payments_from_composed_total(db_session):
    invoice = _create_invoice_with_items(
        db_session,
        descriptions_and_amounts=[
            ("PAGAMENTO EFETUADO", "-850.00"),
            ("PAGAMENTO EFETUADO", "-10691.62"),
            ("DESCONTO NA FATURA - PO", "-646.28"),
            ("COMPRA MERCADO", "500.00"),
            ("IOF COMPRA INTERNACIONAL", "12.50"),
            ("ESTORNO LOJA", "-20.00"),
        ],
        total_amount_brl="-153.78",
    )

    detail = get_credit_card_invoice_detail(db_session, invoice_id=invoice.id)

    assert detail is not None
    assert detail.summary.charge_total_brl == Decimal("512.50")
    assert detail.summary.credit_total_brl == Decimal("-666.28")
    assert detail.summary.payment_total_brl == Decimal("-11541.62")
    assert detail.summary.composed_total_brl == Decimal("-153.78")
    assert detail.summary.difference_to_invoice_total_brl == Decimal("0.00")


