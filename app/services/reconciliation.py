from app.utils.bank_codes import extract_bank_code
from app.utils.normalization import normalize_description


def infer_transaction_kind(source_type: str, description: str, amount: float) -> str:
    d = normalize_description(description)
    if "estorno" in d or "ajuste" in d:
        return "adjustment"
    if "iof" in d:
        return "tax"
    if "ted 102" in d and "eduardo k c" in d:
        return "transfer"
    if extract_bank_code(description):
        return "transfer"
    if "itau black" in d and amount < 0:
        return "credit_card_payment"
    if "fatura" in d and amount < 0:
        return "credit_card_payment"
    if source_type == "credit_card" and amount > 0:
        return "expense"
    if amount > 0:
        return "income"
    return "expense"


def reconciliation_flags(transaction_kind: str) -> dict:
    is_bill = transaction_kind == "credit_card_payment"
    is_adjustment = transaction_kind in {"adjustment", "reversal"}
    should_count = transaction_kind in {"expense", "fee", "tax", "installment"}
    return {
        "is_card_bill_payment": is_bill,
        "is_adjustment": is_adjustment,
        "is_reconciled": is_bill or is_adjustment,
        "should_count_in_spending": should_count,
    }
