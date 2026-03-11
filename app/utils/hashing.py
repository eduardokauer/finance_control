import hashlib


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
