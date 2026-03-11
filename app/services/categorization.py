from app.utils.normalization import normalize_description

RULES_EXACT = {
    "ifood": "Alimentação",
    "uber": "Transporte",
    "droga raia": "Farmácia",
    "drogasil": "Farmácia",
    "netflix": "Assinaturas",
    "spotify": "Assinaturas",
    "google one": "Assinaturas",
    "petlove": "Pets",
    "petz": "Pets",
    "cobasi": "Pets",
    "mercado livre": "Compras",
    "amazon": "Compras",
    "shopee": "Compras",
    "carrefour": "Supermercado",
    "extra": "Supermercado",
    "pao de acucar": "Supermercado",
    "assai": "Supermercado",
    "shell": "Combustível",
    "ipiranga": "Combustível",
    "sem parar": "Pedágio/Estacionamento",
    "conectcar": "Pedágio/Estacionamento",
    "estapar": "Pedágio/Estacionamento",
    "enel": "Serviços da Casa",
    "sabesp": "Serviços da Casa",
    "vivo fibra": "Serviços da Casa",
}

KEYWORDS = {
    "seguro": "Seguros",
    "iof": "IOF e Encargos",
    "estorno": "Ajustes e Estornos",
    "ajuste": "Ajustes e Estornos",
    "desconto na fatura": "Ajustes e Estornos",
}


def categorize(description: str) -> dict:
    normalized = normalize_description(description)
    for pattern, category in RULES_EXACT.items():
        if normalized == pattern:
            return {"category": category, "method": "exact", "confidence": 1.0, "rule": pattern}
    for pattern, category in RULES_EXACT.items():
        if pattern in normalized:
            return {"category": category, "method": "contains", "confidence": 0.9, "rule": pattern}
    for pattern, category in KEYWORDS.items():
        if pattern in normalized:
            return {"category": category, "method": "keyword", "confidence": 0.8, "rule": pattern}
    return {"category": "Não Categorizado", "method": "fallback", "confidence": 0.3, "rule": None}
