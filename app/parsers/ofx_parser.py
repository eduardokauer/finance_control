import re
from datetime import datetime


REQUIRED_TAGS = ["<OFX>", "<BANKTRANLIST>", "<STMTTRN>"]
REQUIRED_TRN_FIELDS = ["TRNTYPE", "DTPOSTED", "TRNAMT", "NAME"]


def validate_ofx_structure(content: str) -> None:
    for tag in REQUIRED_TAGS:
        if tag not in content:
            raise ValueError(f"Missing required tag: {tag}")
    if "<STMTTRN>" not in content:
        raise ValueError("No transactions found")


def parse_ofx(content: str) -> list[dict]:
    validate_ofx_structure(content)
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", content, flags=re.S)
    if not blocks:
        raise ValueError("No transaction blocks")

    items = []
    for block in blocks:
        data = {}
        for field in REQUIRED_TRN_FIELDS + ["FITID"]:
            m = re.search(rf"<{field}>([^<\n\r]+)", block)
            if m:
                data[field.lower()] = m.group(1).strip()
        for required in REQUIRED_TRN_FIELDS:
            if required.lower() not in data:
                raise ValueError(f"Missing transaction field: {required}")
        items.append(
            {
                "external_id": data.get("fitid"),
                "date": datetime.strptime(data["dtposted"][:8], "%Y%m%d").date(),
                "amount": float(data["trnamt"].replace(",", ".")),
                "trntype": data["trntype"].lower(),
                "description": data["name"],
                "raw": block.strip(),
            }
        )
    return items
