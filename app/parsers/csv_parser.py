import csv
from datetime import datetime

EXPECTED_COLUMNS = ["data", "descricao", "valor", "tipo"]


def parse_csv(content: bytes) -> list[dict]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid CSV encoding") from exc

    rows = list(csv.reader(text.splitlines()))
    if not rows:
        raise ValueError("Empty CSV")

    headers = [h.strip().lower() for h in rows[0]]
    if headers != EXPECTED_COLUMNS:
        raise ValueError("Invalid CSV columns or order")

    items = []
    for row in rows[1:]:
        if len(row) != 4:
            raise ValueError("Invalid CSV row length")
        try:
            trn_date = datetime.strptime(row[0].strip(), "%d/%m/%Y").date()
            amount = float(row[2].strip().replace(".", "").replace(",", "."))
        except Exception as exc:
            raise ValueError("Invalid CSV date or value format") from exc
        items.append(
            {
                "external_id": None,
                "date": trn_date,
                "amount": amount,
                "description": row[1].strip(),
                "row_type": row[3].strip().lower(),
                "raw": ",".join(row),
            }
        )
    if not items:
        raise ValueError("No transactions found")
    return items
