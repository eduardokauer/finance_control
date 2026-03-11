from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.parsers.csv_parser import parse_csv
from app.parsers.ofx_parser import parse_ofx
from app.repositories.models import RawTransaction, SourceFile, Transaction
from app.services.categorization import categorize
from app.services.reconciliation import infer_transaction_kind, reconciliation_flags
from app.utils.hashing import canonical_hash, file_hash
from app.utils.normalization import normalize_description


def ingest_file(db: Session, source_type: str, file_name: str, file_path: str, reference_id: str | None):
    raw_content = Path(file_path).read_bytes()
    f_hash = file_hash(raw_content)
    existing_file = db.scalar(select(SourceFile).where(SourceFile.file_hash == f_hash))
    if existing_file:
        return {"status": "duplicate", "message": "Arquivo duplicado", "source_file_id": existing_file.id}

    sf = SourceFile(
        source_type=source_type,
        file_name=file_name,
        file_path=file_path,
        reference_id=reference_id,
        file_hash=f_hash,
        status="processing",
    )
    db.add(sf)
    db.flush()
    try:
        if source_type == "bank_statement":
            parsed = parse_ofx(raw_content.decode("utf-8", errors="ignore"))
        else:
            parsed = parse_csv(raw_content)
    except Exception as exc:
        sf.status = "error"
        sf.error_message = str(exc)
        db.commit()
        raise

    inserted = 0
    for row in parsed:
        db.add(
            RawTransaction(
                source_file_id=sf.id,
                external_id=row.get("external_id"),
                raw_payload=row["raw"],
                transaction_date=row["date"],
                amount=row["amount"],
                description_raw=row["description"],
            )
        )
        normalized = normalize_description(row["description"])
        direction = "credit" if row["amount"] > 0 else "debit"
        c_hash_payload = "|".join(
            [
                "default-account",
                source_type,
                str(row["date"]),
                f"{row['amount']:.2f}",
                direction,
                normalized,
                row.get("external_id") or "",
            ]
        )
        current_hash = canonical_hash(c_hash_payload)
        if row.get("external_id"):
            duplicate_tx = db.scalar(
                select(Transaction.id).where(
                    or_(
                        Transaction.canonical_hash == current_hash,
                        Transaction.external_id == row.get("external_id"),
                    )
                )
            )
        else:
            duplicate_tx = db.scalar(select(Transaction.id).where(Transaction.canonical_hash == current_hash))
        if duplicate_tx:
            continue
        cat = categorize(row["description"])
        kind = infer_transaction_kind(source_type, row["description"], row["amount"])
        flags = reconciliation_flags(kind)
        db.add(
            Transaction(
                source_file_id=sf.id,
                source_type=source_type,
                account_ref="default-account",
                external_id=row.get("external_id"),
                canonical_hash=current_hash,
                transaction_date=row["date"],
                competence_month=row["date"].strftime("%Y-%m"),
                description_raw=row["description"],
                description_normalized=normalized,
                amount=row["amount"],
                direction=direction,
                transaction_kind=kind,
                category=cat["category"],
                categorization_method=cat["method"],
                categorization_confidence=cat["confidence"],
                applied_rule=cat["rule"],
                **flags,
            )
        )
        inserted += 1

    sf.status = "processed"
    db.commit()
    return {"status": "processed", "message": f"Arquivo processado: {inserted} transações novas", "source_file_id": sf.id}
