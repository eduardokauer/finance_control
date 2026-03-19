import csv
import re
from datetime import datetime

from app.utils.normalization import normalize_description

EXPECTED_HEADERS = ["data", "lancamento", "valor"]
INSTALLMENT_PATTERN = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Invalid CSV encoding")


def _normalize_header(value: str) -> str:
    return normalize_description(value).replace(" ", "")


def _resolve_delimiter(sample: str) -> str:
    return ";" if sample.count(";") > sample.count(",") else ","


def _parse_amount(raw_value: str) -> float:
    value = raw_value.strip().replace("R$", "").replace(" ", "")
    if not value:
        raise ValueError("Invalid bill amount")
    normalized = value.replace(".", "").replace(",", ".")
    return float(normalized)


def parse_itau_credit_card_csv(content: bytes) -> list[dict]:
    text = _decode_csv(content)
    if not text.strip():
        raise ValueError("Empty CSV")

    delimiter = _resolve_delimiter(text[:1024])
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        raise ValueError("Empty CSV")

    headers = [_normalize_header(column) for column in rows[0]]
    if headers != EXPECTED_HEADERS:
        raise ValueError("Invalid CSV columns or order")

    items = []
    for index, row in enumerate(rows[1:], start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != 3:
            raise ValueError(f"Invalid CSV row length at line {index}")
        date_raw, description_raw, amount_raw = [cell.strip() for cell in row]
        if not description_raw:
            raise ValueError(f"Empty description at line {index}")
        try:
            purchase_date = datetime.strptime(date_raw, "%d/%m/%Y").date()
        except ValueError as exc:
            raise ValueError(f"Invalid purchase date at line {index}") from exc
        try:
            amount_brl = _parse_amount(amount_raw)
        except ValueError as exc:
            raise ValueError(f"Invalid bill amount at line {index}") from exc

        installment_match = INSTALLMENT_PATTERN.search(description_raw)
        installment_current = None
        installment_total = None
        derived_note = None
        if installment_match:
            installment_current = int(installment_match.group(1))
            installment_total = int(installment_match.group(2))
            derived_note = f"Parcela {installment_current}/{installment_total}"

        items.append(
            {
                "purchase_date": purchase_date,
                "description_raw": description_raw,
                "description_normalized": normalize_description(description_raw),
                "amount_brl": amount_brl,
                "installment_current": installment_current,
                "installment_total": installment_total,
                "is_installment": installment_match is not None,
                "derived_note": derived_note,
            }
        )

    if not items:
        raise ValueError("No invoice items found")

    return items
