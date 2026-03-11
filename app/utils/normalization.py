import re
import unicodedata


def normalize_description(text: str) -> str:
    base = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-zA-Z0-9\s]", " ", base.lower())
    return re.sub(r"\s+", " ", base).strip()
