from app.utils.bank_codes import bank_name_from_description, extract_bank_code
from app.utils.normalization import normalize_description

EXACT_RULES = [
    ("ifood", "Alimentação"),
    ("uber", "Transporte"),
    ("droga raia", "Farmácia"),
    ("drogasil", "Farmácia"),
    ("netflix", "Assinaturas"),
    ("spotify", "Assinaturas"),
    ("google one", "Assinaturas"),
    ("petlove", "Pets"),
    ("petz", "Pets"),
    ("cobasi", "Pets"),
    ("mercado livre", "Compras"),
    ("amazon", "Compras"),
    ("shopee", "Compras"),
    ("carrefour", "Supermercado"),
    ("extra", "Supermercado"),
    ("pao de acucar", "Supermercado"),
    ("assai", "Supermercado"),
    ("shell", "Combustível"),
    ("ipiranga", "Combustível"),
    ("sem parar", "Pedágio/Estacionamento"),
    ("conectcar", "Pedágio/Estacionamento"),
    ("estapar", "Pedágio/Estacionamento"),
    ("enel", "Serviços da Casa"),
    ("sabesp", "Serviços da Casa"),
    ("vivo fibra", "Serviços da Casa"),
]

STRONG_RULES = [
    ("itau black", "Pagamento de Fatura", "contains", 0.99),
    ("eletropaulo", "Serviços da Casa", "contains", 0.96),
    ("telefonica", "Serviços da Casa", "contains", 0.96),
    ("ipva", "Impostos e Taxas", "contains", 0.98),
    ("licenc", "Impostos e Taxas", "contains", 0.95),
    ("socialcondo", "Moradia", "contains", 0.88),
    ("guarida", "Moradia", "contains", 0.88),
    ("psicolo", "Saúde", "contains", 0.85),
    ("faris", "Saúde", "contains", 0.85),
    ("luma", "Saúde", "contains", 0.85),
    ("m a dos", "Saúde", "contains", 0.8),
    ("ewerton", "Moradia", "contains", 0.85),
    ("leticia", "Moradia", "contains", 0.85),
]

KEYWORDS = [
    ("seguro", "Seguros"),
    ("iof", "IOF e Encargos"),
    ("estorno", "Ajustes e Estornos"),
    ("ajuste", "Ajustes e Estornos"),
    ("desconto na fatura", "Ajustes e Estornos"),
]


def categorize(description: str, transaction_kind: str | None = None) -> dict:
    normalized = normalize_description(description)

    if transaction_kind == "credit_card_payment":
        return {
            "category": "Pagamento de Fatura",
            "method": "transaction_kind",
            "confidence": 1.0,
            "rule": "credit_card_payment",
        }

    if transaction_kind == "transfer":
        bank_code = extract_bank_code(description)
        if bank_code:
            bank_name = bank_name_from_description(description)
            rule = f"bank_code:{bank_code}"
            if bank_name:
                rule = f"{rule}:{bank_name}"
            return {
                "category": "Transferências",
                "method": "bank_code",
                "confidence": 0.95,
                "rule": rule,
            }
        return {
            "category": "Transferências",
            "method": "transaction_kind",
            "confidence": 0.95,
            "rule": "transfer",
        }

    for pattern, category in EXACT_RULES:
        if normalized == pattern:
            return {"category": category, "method": "exact", "confidence": 1.0, "rule": pattern}

    for pattern, category, method, confidence in STRONG_RULES:
        if pattern in normalized:
            return {"category": category, "method": method, "confidence": confidence, "rule": pattern}

    for pattern, category in EXACT_RULES:
        if pattern in normalized:
            return {"category": category, "method": "contains", "confidence": 0.9, "rule": pattern}

    for pattern, category in KEYWORDS:
        if pattern in normalized:
            return {"category": category, "method": "keyword", "confidence": 0.8, "rule": pattern}

    return {"category": "Não Categorizado", "method": "fallback", "confidence": 0.3, "rule": None}
