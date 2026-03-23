from app.parsers.csv_parser import parse_csv
from app.parsers.ofx_parser import parse_ofx, validate_ofx_structure
from app.repositories.models import CategorizationRule
from app.services.categorization import categorize
from app.services.classification import classify_credit_card_invoice_charge, classify_transaction
from app.services.reconciliation import infer_transaction_kind, reconciliation_flags
from app.utils.bank_codes import bank_name_from_description, extract_bank_code
from app.utils.hashing import canonical_hash, file_hash
from app.utils.normalization import normalize_description


def test_validate_ofx_structure_ok():
    validate_ofx_structure("<OFX><BANKTRANLIST><STMTTRN></STMTTRN></BANKTRANLIST></OFX>")


def test_validate_ofx_structure_invalid():
    try:
        validate_ofx_structure("<OFX></OFX>")
        assert False
    except ValueError:
        assert True


def test_parse_csv_validation():
    parsed = parse_csv(b"data,descricao,valor,tipo\n07/03/2026,Compra,-1,compra\n")
    assert len(parsed) == 1


def test_normalization():
    assert normalize_description("Drogá-Raia #123") == "droga raia 123"


def test_hashing():
    assert file_hash(b"abc") == file_hash(b"abc")
    assert canonical_hash("x") != canonical_hash("y")


def test_deterministic_categorization():
    result = categorize("Compra Ifood pedido")
    assert result["category"] == "Alimentação"


def test_itau_specific_categorization_rules():
    assert categorize("DA ELETROPAULO 77209859")["category"] == "Serviços da Casa"
    assert categorize("INT IPVA SPTKY5B58PARC05")["category"] == "Impostos e Taxas"
    assert categorize("PIX TRANSF PSICOLO05 02")["category"] == "Saúde"
    assert categorize("PIX TRANSF LETICIA12 02")["category"] == "Moradia"
    assert categorize("PIX TRANSF EWERTON03 02")["category"] == "Moradia"
    assert categorize("ITAU BLACK 3101 1291", transaction_kind="credit_card_payment")["category"] == "Pagamento de Fatura"


def test_transfer_categorization_uses_bank_code():
    result = categorize("MOBILE PAG TIT BANCO 208", transaction_kind="transfer")
    assert result["category"] == "Transferências"
    assert result["method"] == "bank_code"
    assert result["rule"] == "bank_code:208:BTG Pactual"


def test_reconciliation_payment_and_double_count_prevention():
    kind = infer_transaction_kind("bank_statement", "Pagamento Fatura Cartao", -500)
    flags = reconciliation_flags(kind)
    assert flags["is_card_bill_payment"] is True
    assert flags["should_count_in_spending"] is False


def test_itau_black_is_credit_card_payment():
    kind = infer_transaction_kind("bank_statement", "ITAU BLACK 3101 1291", -10445.27)
    flags = reconciliation_flags(kind)
    assert kind == "credit_card_payment"
    assert flags["should_count_in_spending"] is False


def test_income_does_not_count_as_spending():
    flags = reconciliation_flags("income")
    assert flags["should_count_in_spending"] is False


def test_ted_102_is_transfer_between_accounts():
    kind = infer_transaction_kind("bank_statement", "TED 102 0001 EDUARDO K C", 8000.00)
    flags = reconciliation_flags(kind)
    assert kind == "transfer"
    assert flags["should_count_in_spending"] is False


def test_pag_tit_with_bank_code_is_transfer():
    kind = infer_transaction_kind("bank_statement", "MOBILE PAG TIT BANCO 208", -1544.50)
    flags = reconciliation_flags(kind)
    assert kind == "transfer"
    assert flags["should_count_in_spending"] is False


def test_bank_code_extraction():
    assert extract_bank_code("MOBILE PAG TIT BANCO 208") == "208"
    assert bank_name_from_description("PAG TIT INT 033") == "Santander"


def test_parse_ofx_fields():
    ofx = "<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260307<TRNAMT>-10<NAME>Uber<FITID>ABC</STMTTRN></BANKTRANLIST></OFX>"
    parsed = parse_ofx(ofx)
    assert parsed[0]["external_id"] == "ABC"


def test_parse_ofx_uses_memo_when_name_is_absent():
    ofx = "<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260307<TRNAMT>-10<MEMO>PIX TRANSF TESTE<FITID>ABC</STMTTRN></BANKTRANLIST></OFX>"
    parsed = parse_ofx(ofx)
    assert parsed[0]["description"] == "PIX TRANSF TESTE"


def test_manual_rule_flow_uses_income_for_positive_amount(db_session):
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="guarida",
            category_name="Moradia",
            kind_mode="flow",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()

    result = classify_transaction(db_session, "bank_statement", "PIX GUARIDA", 1500.0)
    assert result["category"] == "Moradia"
    assert result["transaction_kind"] == "income"


def test_manual_rule_flow_uses_expense_for_negative_amount(db_session):
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="guarida",
            category_name="Moradia",
            kind_mode="flow",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()

    result = classify_transaction(db_session, "bank_statement", "PIX GUARIDA", -850.0)
    assert result["category"] == "Moradia"
    assert result["transaction_kind"] == "expense"


def test_manual_rule_transfer_forces_transfer_kind(db_session):
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="itau black",
            category_name="Pagamento de Fatura",
            kind_mode="transfer",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()

    result = classify_transaction(db_session, "bank_statement", "ITAU BLACK 3101 1291", -10445.27)
    assert result["category"] == "Pagamento de Fatura"
    assert result["transaction_kind"] == "transfer"


def test_manual_rule_source_scope_can_target_only_invoice_items(db_session):
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="curso plataforma",
            category_name="Educação",
            kind_mode="flow",
            source_scope="credit_card_invoice_item",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()

    invoice_result = classify_credit_card_invoice_charge(db_session, "CURSO PLATAFORMA ONLINE")
    bank_result = classify_transaction(db_session, "bank_statement", "CURSO PLATAFORMA ONLINE", -120.0)

    assert invoice_result["category"] == "Educação"
    assert invoice_result["method"] == "rule"
    assert bank_result["category"] in {"Não Categorizado", "Nao Categorizado"}


def test_manual_rule_source_scope_preserves_bank_statement_behavior(db_session):
    db_session.add(
        CategorizationRule(
            rule_type="contains",
            pattern="favorecido raro",
            category_name="Moradia",
            kind_mode="flow",
            source_scope="bank_statement",
            priority=0,
            is_active=True,
        )
    )
    db_session.commit()

    bank_result = classify_transaction(db_session, "bank_statement", "PIX FAVORECIDO RARO", -850.0)
    invoice_result = classify_credit_card_invoice_charge(db_session, "PIX FAVORECIDO RARO")

    assert bank_result["category"] == "Moradia"
    assert bank_result["method"] == "rule"
    assert invoice_result["category"] in {"Não Categorizado", "Nao Categorizado"}

