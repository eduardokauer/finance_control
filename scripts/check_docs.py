from __future__ import annotations

import argparse
import sys
from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"
HIDDEN_OR_BIDI_CHARS = {
    0x00AD,  # soft hyphen
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x2060,  # word joiner
    0x202A,  # left-to-right embedding
    0x202B,  # right-to-left embedding
    0x202C,  # pop directional formatting
    0x202D,  # left-to-right override
    0x202E,  # right-to-left override
    0x2066,  # left-to-right isolate
    0x2067,  # right-to-left isolate
    0x2068,  # first strong isolate
    0x2069,  # pop directional isolate
    0xFEFF,  # zero width no-break space / BOM
}


def _collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"Caminho inexistente: {path}")
        if path.is_file():
            files.append(path)
            continue
        files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
    return files


def _line_col_from_offset(text: str, offset: int) -> tuple[int, int]:
    line = 1
    column = 1
    for current in text[:offset]:
        if current == "\n":
            line += 1
            column = 1
        else:
            column += 1
    return line, column


def _check_file(path: Path) -> list[str]:
    issues: list[str] = []
    raw = path.read_bytes()

    if raw.startswith(UTF8_BOM):
        issues.append("contém BOM UTF-8 no início do arquivo")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(f"não está em UTF-8 válido ({exc})")
        return issues

    if text and not raw.endswith(b"\n"):
        issues.append("não termina com newline final")

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.rstrip(" \t") != line:
            issues.append(f"linha {line_number}: trailing whitespace")

    if "\ufffd" in text:
        for offset, char in enumerate(text):
            if char == "\ufffd":
                line, column = _line_col_from_offset(text, offset)
                issues.append(f"linha {line}, coluna {column}: contém caractere de substituição (U+FFFD)")

    for offset, char in enumerate(text):
        codepoint = ord(char)
        if codepoint not in HIDDEN_OR_BIDI_CHARS:
            continue
        line, column = _line_col_from_offset(text, offset)
        issues.append(
            f"linha {line}, coluna {column}: contém caractere invisível/bidirecional U+{codepoint:04X}"
        )

    return issues


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Valida a saúde textual de arquivos de documentação."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["docs"],
        help="Arquivos ou diretórios para validar. Padrão: docs",
    )
    args = parser.parse_args(argv)

    try:
        files = _collect_files(args.paths)
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}")
        return 1

    if not files:
        print("[FAIL] Nenhum arquivo encontrado para validar.")
        return 1

    failures = 0
    for path in files:
        issues = _check_file(path)
        if not issues:
            continue
        failures += 1
        print(f"[FAIL] {path}")
        for issue in issues:
            print(f"  - {issue}")

    if failures:
        print(f"\nResultado: {failures} arquivo(s) com problemas.")
        return 1

    print(f"[OK] {len(files)} arquivo(s) validados sem problemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
