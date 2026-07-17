"""Encoding detection and file reading utilities."""

import chardet


def detect_encoding(file_path: str) -> str:
    """Detect the encoding of a text file using chardet.

    Reads up to 64KB for encoding detection.
    Returns a normalized encoding name.
    """
    with open(file_path, "rb") as f:
        raw_data = f.read(65536)

    result = chardet.detect(raw_data)
    encoding = result.get("encoding")

    if not encoding:
        return "utf-8"

    encoding = encoding.lower()

    # chardet sometimes returns unreliable results for these
    if encoding in ("iso-8859-1", "windows-1252"):
        return "utf-8"

    return encoding


def read_file_with_encoding(file_path: str, encoding: str | None = None) -> str:
    """Read a text file, optionally specifying encoding.

    If encoding is None, auto-detection is used.
    Falls back through common encodings if detection fails.
    """
    if encoding and encoding != "auto":
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            pass  # Fall through to auto-detection

    # Auto-detect
    detected = detect_encoding(file_path)
    try:
        with open(file_path, "r", encoding=detected) as f:
            return f.read()
    except (UnicodeDecodeError, UnicodeError):
        pass

    # Fallback chain
    for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue

    # Ultimate fallback: replace invalid chars
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()
