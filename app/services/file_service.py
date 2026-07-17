"""File service: scan, parse chapters, and extract text content."""

import os
import re
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.encoding import read_file_with_encoding
from app.models import NovelInfo, ChapterInfo

# ─── Chapter Detection Patterns (ordered by priority) ─────────

CHAPTER_PATTERNS = [
    # Chinese: 第X章, 第X回, 第X节, 第X部, 第X卷
    re.compile(r"第[一二三四五六七八九十百千万零〇0-9]+[章回节部卷]", re.IGNORECASE),
    # Chinese: 序章, 序幕, 楔子, 尾声
    re.compile(r"^[序楔尾][章节言曲]?$|^序幕$|^尾声$", re.MULTILINE),
    # English: Chapter X / Chapter IX
    re.compile(r"chapter\s+[0-9]+", re.IGNORECASE),
    re.compile(r"chapter\s+[ivxlcdm]+", re.IGNORECASE),
    # Numbered lines: 1. / 1、 / [1] / 1） / 1》
    re.compile(r"^\s*\d+[.、）\)）》〕]" , re.MULTILINE),
    # Chinese numbered: 一、 / 一. / （一） / 一）
    re.compile(r"^[一二三四五六七八九十]+[.、）\)]", re.MULTILINE),
    # Markdown headings
    re.compile(r"^#{1,3}\s+\S", re.MULTILINE),
    # Separator lines
    re.compile(r"^[-*=]{3,}$", re.MULTILINE),
]


def _safe_path(filename: str) -> Path:
    """Resolve filename safely within the configured directory.

    Prevents path traversal attacks by stripping directory components
    and verifying the resolved path is within the allowed directory.
    """
    safe_name = os.path.basename(filename)
    novels_dir = settings.text_files_dir.resolve()
    full_path = (novels_dir / safe_name).resolve()

    if not str(full_path).startswith(str(novels_dir)):
        raise ValueError("Path traversal detected: invalid file path")

    return full_path


def _estimate_chapters(text: str) -> int:
    """Count likely chapter boundaries in the text."""
    seen_positions: set[int] = set()
    count = 0

    for pattern in CHAPTER_PATTERNS:
        for match in pattern.finditer(text):
            pos = match.start()
            # Avoid counting matches at the same position
            if not any(abs(pos - p) < 5 for p in seen_positions):
                seen_positions.add(pos)
                count += 1

    return max(1, count)


def _parse_chapters(text: str) -> list[ChapterInfo]:
    """Parse text into a list of chapters with their start positions."""
    boundaries: list[tuple[int, str]] = []

    for pattern in CHAPTER_PATTERNS:
        for match in pattern.finditer(text):
            pos = match.start()
            title = match.group().strip()
            # Avoid near-duplicates (within 3 chars)
            if not any(abs(pos - b[0]) < 3 for b in boundaries):
                boundaries.append((pos, title))

    # Sort by position in file
    boundaries.sort(key=lambda x: x[0])

    if not boundaries:
        return [ChapterInfo(chapter_number=1, title="（全文）", start_pos=0)]

    chapters: list[ChapterInfo] = []
    for i, (pos, title) in enumerate(boundaries):
        chapters.append(ChapterInfo(
            chapter_number=i + 1,
            title=title,
            start_pos=pos,
        ))

    return chapters


# ─── Public API ───────────────────────────────────────────────

def list_novel_files(
    page: int = 1,
    page_size: int = 20,
    ext: str | None = None,
) -> tuple[list[NovelInfo], int]:
    """List novel files in the configured directory.

    Returns (files, total_count).
    """
    novels_dir = settings.text_files_dir
    if not novels_dir.exists():
        return [], 0

    allowed_exts = settings.text_file_extensions_list
    files: list[NovelInfo] = []

    for f in sorted(novels_dir.iterdir()):
        if not f.is_file():
            continue

        file_ext = f.suffix.lower()

        # Filter by specific extension if provided
        if ext:
            if file_ext != ext.lower():
                continue
        else:
            if file_ext not in allowed_exts:
                continue

        # Estimate chapters
        try:
            text = read_file_with_encoding(str(f))
            est_chapters = _estimate_chapters(text)
        except Exception:
            est_chapters = 0

        stat = f.stat()
        import datetime
        files.append(NovelInfo(
            filename=f.name,
            file_size=stat.st_size,
            modified_time=datetime.datetime.fromtimestamp(stat.st_mtime),
            estimated_chapters=est_chapters,
        ))

    # Sort by filename
    files.sort(key=lambda x: x.filename)

    total = len(files)
    start = (page - 1) * page_size
    end = start + page_size
    page_files = files[start:end]

    return page_files, total


def get_chapters(filename: str) -> list[ChapterInfo]:
    """Get chapter list for a given file."""
    file_path = _safe_path(filename)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")

    text = read_file_with_encoding(str(file_path))
    return _parse_chapters(text)


def get_content(
    filename: str,
    start: int = 0,
    offset: int = 2000,
    chapter: int | None = None,
) -> dict:
    """Get text content from a file.

    Supports both raw character offset and chapter-based navigation.
    Returns a dict matching ContentResponse schema.
    """
    file_path = _safe_path(filename)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")

    text = read_file_with_encoding(str(file_path))
    total_length = len(text)
    effective_start = start
    chapter_title: str | None = None

    if chapter is not None:
        chapters = _parse_chapters(text)
        if chapter < 1 or chapter > len(chapters):
            raise ValueError(
                f"章节 {chapter} 不存在，文件共有 {len(chapters)} 章"
            )
        ch = chapters[chapter - 1]
        effective_start = ch.start_pos + start
        chapter_title = ch.title

    # Bounds checking
    if effective_start < 0:
        effective_start = 0
    if effective_start >= total_length:
        effective_start = max(0, total_length - 1)

    end = effective_start + offset
    if end > total_length:
        end = total_length

    content = text[effective_start:end]

    return {
        "filename": filename,
        "start": effective_start,
        "offset": len(content),
        "total_length": total_length,
        "content": content,
        "chapter_title": chapter_title,
    }


def get_chapter_content(
    filename: str,
    chapter_number: int,
    start: int = 0,
    offset: int | None = None,
) -> dict:
    """获取指定章节的文本内容，支持章节内偏移。

    从章节起始位置开始截取，到下一章开始位置（或文件末尾）结束。
    可通过 start 参数指定章节内的字符偏移起始位置。
    可通过 offset 参数限制返回字符数。
    返回 dict 与 ContentResponse schema 兼容。
    """
    chapters = get_chapters(filename)
    if chapter_number < 1 or chapter_number > len(chapters):
        raise ValueError(
            f"章节 {chapter_number} 不存在，文件共有 {len(chapters)} 章"
        )

    ch = chapters[chapter_number - 1]

    # 计算章节结束位置：下一章起始位置，或文件末尾
    file_path = _safe_path(filename)
    text = read_file_with_encoding(str(file_path))
    total_length = len(text)

    if chapter_number < len(chapters):
        chapter_end = chapters[chapter_number].start_pos
    else:
        chapter_end = total_length

    # 有效起始位置 = 章节起始 + 章节内偏移
    effective_start = ch.start_pos + start
    chapter_absolute_end = chapter_end

    # 边界检查
    if effective_start < ch.start_pos:
        effective_start = ch.start_pos
    if effective_start >= chapter_absolute_end:
        effective_start = chapter_absolute_end - 1
    if effective_start < 0:
        effective_start = 0

    # 计算长度：不指定 offset 则到章节末尾；指定则取较小值
    available = chapter_absolute_end - effective_start
    if offset is not None:
        length = min(available, offset)
    else:
        length = available

    end_pos = effective_start + length
    content = text[effective_start:end_pos]

    return {
        "filename": filename,
        "start": effective_start,
        "offset": len(content),
        "total_length": total_length,
        "content": content,
        "chapter_title": ch.title,
    }
