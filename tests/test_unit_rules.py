from app.parsers.csv_parser import parse_csv
from app.parsers.ofx_parser import parse_ofx, validate_ofx_structure
from app.services.categorization import categorize
from app.services.reconciliation import infer_transaction_kind, reconciliation_flags
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


def test_reconciliation_payment_and_double_count_prevention():
    kind = infer_transaction_kind("bank_statement", "Pagamento Fatura Cartao", -500)
    flags = reconciliation_flags(kind)
    assert flags["is_card_bill_payment"] is True
    assert flags["should_count_in_spending"] is False


def test_parse_ofx_fields():
    ofx = "<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260307<TRNAMT>-10<NAME>Uber<FITID>ABC</STMTTRN></BANKTRANLIST></OFX>"
    parsed = parse_ofx(ofx)
    assert parsed[0]["external_id"] == "ABC"
