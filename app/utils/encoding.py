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

    # gb2312 is a subset of gbk; prefer gbk for better compatibility
    if encoding == "gb2312":
        return "gbk"

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

    # Try detected encoding first
    try:
        with open(file_path, "r", encoding=detected) as f:
            text = f.read()
        # Validate: if most chars are replacement-like, encoding is likely wrong
        if _looks_like_garbled(text):
            raise UnicodeDecodeError(detected, b"", 0, 1, "garbled output")
        return text
    except (UnicodeDecodeError, UnicodeError):
        pass

    # Fallback chain (common Chinese + universal encodings)
    for enc in ("utf-8", "gbk", "gb18030", "latin-1"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                text = f.read()
            if enc == "latin-1" and _looks_like_garbled(text):
                continue
            return text
        except (UnicodeDecodeError, UnicodeError):
            continue

    # Ultimate fallback: replace invalid chars
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _looks_like_garbled(text: str) -> bool:
    """Check if text looks like garbled/mojibake output.

    If the text has many non-CJK non-ASCII chars in a row, it's likely
    decoded with the wrong encoding.
    """
    if not text:
        return False
    sample = text[:2000]
    # Count suspicious chars: high bytes that are NOT valid CJK ranges
    suspicious = 0
    for ch in sample:
        code = ord(ch)
        # Skip ASCII, CJK Unified Ideographs, CJK punctuation, common symbols
        if code < 128:
            continue
        if 0x4E00 <= code <= 0x9FFF:  # CJK
            continue
        if 0x3000 <= code <= 0x303F:  # CJK symbols
            continue
        if 0xFF00 <= code <= 0xFFEF:  # Fullwidth forms
            continue
        if 0x2000 <= code <= 0x206F:  # General punctuation
            continue
        suspicious += 1
    return suspicious > len(sample) * 0.3
