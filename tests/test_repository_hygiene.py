from pathlib import Path

TEXT_SUFFIXES = {
    ".py",
    ".html",
    ".sql",
    ".md",
    ".yml",
    ".yaml",
    ".ini",
    ".txt",
    ".csv",
    ".ofx",
}
FINAL_NEWLINE_SUFFIXES = {
    ".py",
    ".html",
    ".sql",
    ".md",
    ".yml",
    ".yaml",
    ".ini",
    ".txt",
}
ROOT_TEXT_FILES = {
    "Dockerfile",
    "Makefile",
    "README.md",
    "docker-compose.yml",
    "pytest.ini",
    "requirements.txt",
    ".env.example",
}
ROOT_FILES_REQUIRING_FINAL_NEWLINE = ROOT_TEXT_FILES - {"Dockerfile", "Makefile"}
MOJIBAKE_MARKERS = (
    "\u00c3\u00a1",
    "\u00c3\u00a2",
    "\u00c3\u00a3",
    "\u00c3\u00a4",
    "\u00c3\u00a7",
    "\u00c3\u00a9",
    "\u00c3\u00aa",
    "\u00c3\u00ad",
    "\u00c3\u00b3",
    "\u00c3\u00b4",
    "\u00c3\u00b5",
    "\u00c3\u00ba",
    "\u00c3\u20ac",
    "\u00c3\ufffd",
    "\u00c3\u0192",
    "\u00c3\u2021",
    "\u00c2\u00a3",
    "\u00c2\u00ba",
    "\u00c2\u00aa",
    "\u00c2\u00b0",
    "\u00c2\u00a7",
    "\u00ef\u00bb\u00bf",
)
SCAN_ROOTS = (
    Path("app"),
    Path("tests"),
    Path("supabase") / "migrations",
)


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                files.append(path)
    for name in ROOT_TEXT_FILES:
        path = Path(name)
        if path.exists() and path.is_file():
            files.append(path)
    return sorted(set(files))


def _requires_trailing_newline(path: Path) -> bool:
    if path.parent == Path('.'):
        return path.name in ROOT_FILES_REQUIRING_FINAL_NEWLINE
    return path.suffix.lower() in FINAL_NEWLINE_SUFFIXES


def test_repository_text_files_are_utf8_without_bom_or_mojibake():
    failures: list[str] = []

    for path in _iter_text_files():
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            failures.append(f"{path}: has UTF-8 BOM")

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{path}: not valid UTF-8 ({exc})")
            continue

        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                failures.append(f"{path}: contains mojibake marker {marker!r}")
                break

        if raw and _requires_trailing_newline(path) and not text.endswith("\n"):
            failures.append(f"{path}: missing trailing newline")

    assert not failures, "\n".join(failures)
