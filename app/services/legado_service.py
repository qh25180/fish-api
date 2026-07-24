"""Legado 映射服务：将 QHAPI 内部数据模型转为 Legado 兼容格式。"""

import json
import re
import time
from pathlib import Path

from app.config import settings
from app.services.file_service import (
    list_novel_files,
    get_chapters as qhapi_get_chapters,
    _parse_chapters,
    _safe_path,
    get_content,
)
from app.utils.encoding import read_file_with_encoding
from app.legado_models import LegadoBook, LegadoChapter


# ─── 进度持久化 ─────────────────────────────────────

def _progress_file() -> Path:
    """进度文件路径。"""
    return settings.text_files_dir / ".legado_progress.json"


def _load_progress() -> dict:
    """读取进度 JSON，不存在或损坏返回空 dict。"""
    path = _progress_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_progress(data: dict):
    """原子写入进度 JSON（先写临时文件再 rename）。"""
    path = _progress_file()
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


# ─── 书架 ───────────────────────────────────────────

def _load_hidden_books() -> set:
    """读取隐藏书籍列表。"""
    path = settings.text_files_dir / ".hidden_books.json"
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def get_bookshelf() -> list[LegadoBook]:
    """获取书架列表（所有文本文件 → LegadoBook 列表，排除隐藏书籍）。"""
    files, _ = list_novel_files(page=1, page_size=9999)
    hidden = _load_hidden_books()
    return [_file_to_legado_book(f.filename, f.estimated_chapters)
            for f in files if Path(f.filename).stem not in hidden]


def _file_to_legado_book(filename: str, total_chapters: int) -> LegadoBook:
    """将单个文件转为 LegadoBook，读取已保存的阅读进度。"""
    name = Path(filename).stem

    # 尝试读取第一章标题作为默认 durChapterTitle
    try:
        chapters = qhapi_get_chapters(filename)
        first_chapter_title = chapters[0].title if chapters else ""
    except Exception:
        first_chapter_title = ""

    # 读取已保存的进度
    progress = _load_progress()
    book_progress = progress.get(name, {})

    # 尝试从文件名 + 文件内容提取作者
    from app.utils.meta_util import extract_meta
    from app.utils.encoding import detect_encoding
    meta = extract_meta(filename)
    if meta["author"] == "未知作者":
        # 文件名提取失败 → 读文件头
        try:
            file_path = settings.text_files_dir / filename
            if file_path.exists():
                raw = file_path.read_bytes()[:4096]
                enc = detect_encoding(str(file_path))
                head = raw.decode(enc, errors="replace")
                meta = extract_meta(filename, head)
        except Exception:
            pass

    author = meta["author"]
    # 已保存的真实作者优先，未知作者则用提取到的
    saved_author = book_progress.get("author")
    if saved_author and saved_author != "未知作者":
        author = saved_author
    elif author and author != "未知作者":
        # 提取到真实作者，存到进度文件中
        progress[name] = {**book_progress, "author": author}
        _save_progress(progress)

    return LegadoBook(
        name=name,
        author=author,
        bookUrl=filename,
        totalChapterNum=total_chapters,
        durChapterTitle=book_progress.get("durChapterTitle") or first_chapter_title,
        durChapterIndex=book_progress.get("durChapterIndex", 0),
        durChapterPos=book_progress.get("durChapterPos", 0),
        durChapterTime=book_progress.get("durChapterTime", 0),
    )


# ─── 章节列表 ───────────────────────────────────────

def get_chapter_list(book_url: str) -> list[LegadoChapter]:
    """获取指定文件的章节列表 → LegadoChapter 列表。"""
    chapters = qhapi_get_chapters(book_url)
    return [
        LegadoChapter(
            title=ch.title,
            index=i,
            url=f"{book_url}#{i}",
            bookUrl=book_url,
        )
        for i, ch in enumerate(chapters)
    ]


# ─── 章节内容 ───────────────────────────────────────

def get_book_content(book_url: str, chapter_index: int) -> str:
    """获取指定章节的完整文本内容（不截断）。

    返回纯文本字符串，插件会自己按 snippetLength 截断。
    """
    result = get_content(
        filename=book_url,
        start=0,
        offset=999999999,
        chapter=chapter_index + 1,
    )
    return result["content"]


# ─── 进度保存 ───────────────────────────────────────

def save_book_progress(
    name: str,
    author: str,
    dur_chapter_index: int,
    dur_chapter_pos: int,
    dur_chapter_title: str = "",
    dur_chapter_time: int = 0,
) -> None:
    """保存阅读进度到 JSON 文件。"""
    progress = _load_progress()
    progress[name] = {
        "durChapterIndex": dur_chapter_index,
        "durChapterPos": dur_chapter_pos,
        "durChapterTitle": dur_chapter_title,
        "durChapterTime": dur_chapter_time or int(time.time() * 1000),
        "author": author,
    }
    _save_progress(progress)


def _normalize_text(text: str) -> str:
    """规范化文本：去除多余空格、标点差异。"""
    # 去除所有空白字符
    text = re.sub(r"\s+", "", text)
    # 统一标点
    text = text.replace("？", "?").replace("！", "!").replace("，", ",")
    return text


def save_progress_by_chapter(book_url: str, chapter: str) -> None:
    """根据章节标题或序号，将进度保存到该章节起始位置。

    chapter 支持多种格式：
    - 数字字符串（如 "5"）→ 按 1-based 序号匹配
    - 章节号（如 "第一章"）→ 按章节序号匹配
    - 标题关键词（如 "启示"）→ 模糊匹配章节标题
    - 完整标题（如 "第一章 外乡人"）→ 忽略空格模糊匹配
    """
    name = Path(book_url).stem
    chapters = qhapi_get_chapters(book_url)
    if not chapters:
        raise ValueError("章节目录为空")

    # 尝试数字序号匹配
    matched = None
    if chapter.strip().isdigit():
        idx = int(chapter.strip())
        if 1 <= idx <= len(chapters):
            matched = chapters[idx - 1]

    # 尝试章节号匹配（如 "第一章" → 匹配以"第一章"开头的标题）
    if matched is None:
        chapter_norm = _normalize_text(chapter)
        for ch in chapters:
            ch_norm = _normalize_text(ch.title)
            if ch_norm.startswith(chapter_norm):
                matched = ch
                break

    # 尝试标题模糊匹配（忽略空格）
    if matched is None:
        chapter_norm = _normalize_text(chapter)
        for ch in chapters:
            ch_norm = _normalize_text(ch.title)
            if chapter_norm in ch_norm:
                matched = ch
                break

    if matched is None:
        raise ValueError(f"未找到匹配的章节: {chapter}")

    # 找到对应的 Legado 章节索引（0-based）
    chapter_index = next(
        i for i, ch in enumerate(chapters) if ch.start_pos == matched.start_pos
    )

    progress = _load_progress()
    progress[name] = {
        "durChapterIndex": chapter_index,
        "durChapterPos": 0,
        "durChapterTitle": matched.title,
        "durChapterTime": int(time.time() * 1000),
    }
    _save_progress(progress)
