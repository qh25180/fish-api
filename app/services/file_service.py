"""File service: scan, parse chapters, and extract text content."""

import os
import re
import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.encoding import read_file_with_encoding, detect_encoding
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


def _is_likely_chapter_title(text: str, match: re.Match) -> bool:
    """判断正则匹配结果是否为真正的章节标题。

    验证规则：
    1. 匹配位置必须在行首（允许前导空白、常见括号）
    2. 所在行不能过长
    3. 不在引号内部
    4. 数字编号不能是小数（如 1.5 / 9.2）
    5. 行不能全是装饰符（------, ======）
    6. 匹配后紧跟逗号句号 → 是正文讨论章节，不是标题
    """
    pos = match.start()

    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    line_stripped = line.strip()

    # ① 空行或过长 → 不是标题
    if not line_stripped or len(line_stripped) > 60:
        return False

    # ② 行全是装饰符（---, ===, ***）→ 不是标题
    if all(c in "=-*_—～~·" for c in line_stripped):
        return False

    # ③ 对于"部"和"卷"标题，行必须很短（≤25字），否则是正文误匹配
    match_text = match.group()
    if any(suffix in match_text for suffix in ("部", "卷")):
        if len(line_stripped) > 25:
            return False

    # ④ 匹配前到行首之间只能有空白或常见括号/分隔符前缀
    before_match = text[line_start:pos]
    if before_match.strip():
        stripped_before = before_match.strip()
        allowed_brackets = set("【（〔［<《「『")
        if stripped_before not in allowed_brackets and not re.match(r"^[-=*]{2,}$", stripped_before):
            return False

    # ⑤ 检查匹配位置是否在引号内部（只看同一行内）
    line_before = text[line_start:pos]
    if line_before.count('"') % 2 == 1:
        return False
    if line_before.count('\u201c') != line_before.count('\u201d'):
        return False
    if line_before.count('\u300c') != line_before.count('\u300d'):
        return False

    # ⑥ 匹配后紧跟逗号/句号等 → 是正文"第X章"引用，不是标题
    after_on_line = line[match.end():].strip()
    if after_on_line and after_on_line[0] in "，。！？；：,":
        return False

    # ⑦ 数字编号后紧跟数字 → 是小数（如 "1." 在 "1.5万" 中），不是标题
    num_dot = re.match(r"\s*(\d+)[.]", line_stripped)
    if num_dot and not line_stripped.endswith(num_dot.group(0).strip()):
        after_dot = line_stripped[num_dot.end():num_dot.end() + 1]
        if after_dot and after_dot.isdigit():
            return False

    # ⑧ 行结尾是中文冒号/英文冒号 → 附录标签不是章节标题
    if line_stripped.endswith(("：", ":")):
        return False

    return True


def _estimate_chapters(text: str) -> int:
    """Count likely chapter boundaries in the text."""
    seen_positions: set[int] = set()
    count = 0

    for pattern in CHAPTER_PATTERNS:
        for match in pattern.finditer(text):
            pos = match.start()
            if not _is_likely_chapter_title(text, match):
                continue
            if not any(abs(pos - p) < 5 for p in seen_positions):
                seen_positions.add(pos)
                count += 1

    return max(1, count)


def _extract_chapter_title(text: str, match_start: int, match_end: int) -> str:
    """从行中提取干净的章节标题。

    处理正文和标题在同一行的情况：
    \"第三十三章摆渡人卢米安点了点头\" → \"第三十三章 摆渡人\"
    \"第一章 穿越\" → \"第一章 穿越\"
    """
    line_start = text.rfind("\n", 0, match_start) + 1
    line_end = text.find("\n", match_start)
    if line_end == -1:
        line_end = len(text)
    full_line = text[line_start:line_end].strip()
    match_text = text[match_start:match_end]

    # 整行就是匹配文本本身（如 "---", "===="）或只多了装饰
    if len(full_line) <= len(match_text) + 2:
        return full_line if len(full_line) > len(match_text) else match_text

    # 获取匹配后的内容
    after = full_line[match_end - line_start:].strip()

    # 如果匹配后内容很短（≤15字）→ 全行作为标题
    if len(after) <= 15:
        return full_line

    # 正文和标题在同一行 → 找到句子边界截断
    # 策略：在第3~15字间找第一个句尾标点
    cut_pos = -1
    for i in range(3, min(len(after), 15)):
        if after[i] in "，。！？；：、":
            cut_pos = i
            break

    if cut_pos > 0:
        title = match_text + " " + after[:cut_pos]
    else:
        # 没有标点，取前 8 字
        title = match_text + " " + after[:8]

    return title.strip()


_TITLE_CLEAN_PATTERNS = [
    re.compile(r"\s*\([^)]*(?:月票|打赏|感谢|求票|求推荐)[^)]*\)$"),
    re.compile(r"\s*（[^）]*(?:月票|打赏|感谢|求票|求推荐)[^）]*）$"),
]


def _clean_chapter_title(title: str) -> str:
    """清理章节标题中的拉票/打赏后缀。"""
    for pattern in _TITLE_CLEAN_PATTERNS:
        title = pattern.sub("", title).strip()
    return title


def _parse_chapters(text: str) -> list[ChapterInfo]:
    """Parse text into a list of chapters with their start positions."""
    boundaries: list[tuple[int, str]] = []

    for pattern in CHAPTER_PATTERNS:
        for match in pattern.finditer(text):
            if not _is_likely_chapter_title(text, match):
                continue

            pos = match.start()
            title = _extract_chapter_title(text, match.start(), match.end())
            title = _clean_chapter_title(title)

            # 装饰符单独成行 → 跳过
            if all(c in "=-*_—～~·" for c in title):
                continue

            # Avoid near-duplicates (within 3 chars)
            if not any(abs(pos - b[0]) < 3 for b in boundaries):
                boundaries.append((pos, title))

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


def _estimate_chapters_from_head(file_path: Path) -> int:
    """仅读取文件前 64KB 估算章节数，避免大文件全文读取。"""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(65536)
        detected = detect_encoding(str(file_path))
        text = raw.decode(detected, errors="replace")
        return _estimate_chapters(text)
    except Exception:
        return 1


# ─── Cache（LRU 缓存，避免同一文件反复读取+解析）───────────────

# 单个文件最大读取字节数（100 MB），防止 OOM
MAX_FILE_READ_SIZE = 100 * 1024 * 1024


@lru_cache(maxsize=16)
def _read_and_parse_cached(file_path_str: str) -> tuple[str, tuple]:
    """读取文件全文并解析章节，结果由 LRU 缓存。

    返回 (text, chapters_tuple)，chapters_tuple 不可变以便缓存。
    """
    file_size = Path(file_path_str).stat().st_size
    if file_size > MAX_FILE_READ_SIZE:
        raise ValueError(
            f"文件过大（{file_size / 1024 / 1024:.0f}MB），"
            f"超过限制 {MAX_FILE_READ_SIZE / 1024 / 1024}MB"
        )
    text = read_file_with_encoding(file_path_str)
    chapters = _parse_chapters(text)
    return text, tuple(chapters)


def _get_cached_text_and_chapters(file_path: Path) -> tuple[str, list]:
    """从缓存获取文件文本和章节列表。"""
    text, chapters_tuple = _read_and_parse_cached(str(file_path))
    return text, list(chapters_tuple)


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

        # Estimate chapters（仅读文件头 64KB 以提升性能）
        est_chapters = _estimate_chapters_from_head(f)

        stat = f.stat()
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

    _, chapters = _get_cached_text_and_chapters(file_path)
    return chapters


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

    text, chapters = _get_cached_text_and_chapters(file_path)
    total_length = len(text)
    effective_start = start
    chapter_title: str | None = None

    if chapter is not None:
        if chapter < 1 or chapter > len(chapters):
            raise ValueError(
                f"章节 {chapter} 不存在，文件共有 {len(chapters)} 章"
            )
        ch = chapters[chapter - 1]

        # 计算章节结束位置：下一章开头，或文件末尾
        if chapter < len(chapters):
            chapter_end_pos = chapters[chapter].start_pos
        else:
            chapter_end_pos = total_length

        effective_start = ch.start_pos + start

        # 章节内边界检查
        if start < 0:
            effective_start = ch.start_pos
        if effective_start >= chapter_end_pos:
            effective_start = chapter_end_pos - 1
        if effective_start < 0:
            effective_start = 0

        chapter_title = ch.title

        end = effective_start + offset
        if end > chapter_end_pos:
            end = chapter_end_pos
    else:
        # 整书偏移：边界检查
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
    file_path = _safe_path(filename)
    text, chapters = _get_cached_text_and_chapters(file_path)

    if chapter_number < 1 or chapter_number > len(chapters):
        raise ValueError(
            f"章节 {chapter_number} 不存在，文件共有 {len(chapters)} 章"
        )

    ch = chapters[chapter_number - 1]
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
