import re

from app.utils.normalization import normalize_description

# Brazilian COMPE codes. The structure is intentionally small and can be expanded as
# new bank codes appear in the imported statements.
BANK_CODE_NAMES = {
    "001": "Banco do Brasil",
    "033": "Santander",
    "041": "Banrisul",
    "102": "XP",
    "104": "Caixa",
    "208": "BTG Pactual",
    "237": "Bradesco",
    "260": "Nubank",
    "341": "Itau",
    "403": "Cora",
}


def extract_bank_code(description: str) -> str | None:
    normalized = normalize_description(description)
    match = re.search(r"(?:pag tit banco|pag tit int)\s+(\d{3})\b", normalized)
    if match:
        return match.group(1)
    return None


def bank_name_from_description(description: str) -> str | None:
    bank_code = extract_bank_code(description)
    if not bank_code:
        return None
    return BANK_CODE_NAMES.get(bank_code)
