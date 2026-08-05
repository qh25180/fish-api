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
from app.services import meta_cache
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


def get_bookshelf(page: int = 1, page_size: int = 0) -> list[LegadoBook]:
    """获取书架列表（所有文本文件 → LegadoBook 列表，排除隐藏书籍）。

    page/page_size 用于可选分页；page_size<=0 表示全量返回（默认，兼容现有调用）。
    """
    if page_size and page_size > 0:
        files, _ = list_novel_files(page=page, page_size=page_size)
    else:
        files, _ = list_novel_files(page=1, page_size=9999)
    hidden = _load_hidden_books()
    # 进度文件循环外只读一次（避免每本书重复读盘+JSON解析）
    progress = _load_progress()
    return [_file_to_legado_book(f.filename, f.estimated_chapters, progress)
            for f in files if Path(f.filename).stem not in hidden]


def _file_to_legado_book(filename: str, total_chapters: int, progress: dict | None = None) -> LegadoBook:
    """将单个文件转为 LegadoBook，读取已保存的阅读进度。

    progress 由 get_bookshelf 循环外传入（仅读一次）；作者/章节数/首标题优先查指纹缓存。
    """
    name = Path(filename).stem
    progress = progress if progress is not None else _load_progress()
    book_progress = progress.get(name, {})

    # 尝试读取第一章标题作为默认 durChapterTitle（优先指纹缓存，避免读全文）
    first_chapter_title = ""
    meta = None
    try:
        file_path = settings.text_files_dir / filename
        fp = meta_cache.fingerprint(file_path)
        meta = meta_cache.get_meta(filename, fp)
        if meta:
            first_chapter_title = meta.get("first_chapter_title", "") or ""
            # 缓存有章节数但未传入（分页场景 total_chapters 为估算值）→ 用缓存的精确章节数
            if meta.get("chapter_count"):
                total_chapters = meta["chapter_count"]
    except (OSError, TypeError):
        pass

    if not first_chapter_title:
        # 缓存没有首标题 → 读章节缓存或全文（会顺带写缓存）
        try:
            chapters = qhapi_get_chapters(filename)
            first_chapter_title = chapters[0].title if chapters else ""
            # 已解析出精确章节数 → 更新 total_chapters（冷缓存首次补齐）
            if chapters:
                total_chapters = len(chapters)
        except Exception:
            first_chapter_title = ""

    # 尝试从文件名 + 文件内容提取作者（优先指纹缓存）
    if meta and meta.get("author") and meta["author"] != "未知作者":
        author = meta["author"]
    else:
        from app.utils.meta_util import extract_meta
        from app.utils.encoding import detect_encoding
        author = extract_meta(filename)["author"]
        if author == "未知作者":
            # 文件名提取失败 → 读文件头
            try:
                file_path = settings.text_files_dir / filename
                if file_path.exists():
                    raw = file_path.read_bytes()[:4096]
                    enc = detect_encoding(str(file_path))
                    head = raw.decode(enc, errors="replace")
                    author = extract_meta(filename, head)["author"]
            except Exception:
                pass

    # 已保存的真实作者优先，未知作者则用提取到的
    saved_author = book_progress.get("author")
    if saved_author and saved_author != "未知作者":
        # 修复历史乱码：若作者是双重 UTF-8 编码（如 'å\x88\x98...'），尝试还原
        # （latin-1 → utf-8 二次解码成功且含中文视为乱码）
        fixed = _fix_double_encoded(saved_author)
        if fixed is not None:
            author = fixed
            # 仅当修复结果与现有值不同才写盘（避免每请求重复写进度文件）
            if book_progress.get("author") != fixed:
                progress[name] = {**book_progress, "author": fixed}
                _save_progress(progress)
        else:
            author = saved_author
    elif author and author != "未知作者":
        # 提取到真实作者，仅当进度文件中尚未保存时才写入（避免每次请求写盘）
        if book_progress.get("author") != author:
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

def _sanitize_field(value: str, max_len: int = 50) -> str:
    """净化 Legado 外部传入的字段：去 HTML 标签/控制字符、限制长度，防存储型 XSS。"""
    if not value:
        return ""
    # 去标签（<...>）
    value = re.sub(r"<[^>]*>", "", value)
    # 去控制字符（含 CRLF）
    value = re.sub(r"[\x00-\x1f\x7f]", "", value)
    return value.strip()[:max_len]


# 进度条目数上限（防匿名接口无限写盘 DoS）
_MAX_PROGRESS_ENTRIES = 5000


def save_book_progress(
    name: str,
    author: str,
    dur_chapter_index: int,
    dur_chapter_pos: int,
    dur_chapter_title: str = "",
    dur_chapter_time: int = 0,
) -> None:
    """保存阅读进度到 JSON 文件（字段净化防存储型 XSS）。"""
    # 净化外部输入：书名/作者/章节标题去标签、限长（Legado 接口无认证，须防御）
    name = _sanitize_field(name, 200)
    author = _sanitize_field(author, 50)
    dur_chapter_title = _sanitize_field(dur_chapter_title, 200)
    if not name:
        return
    progress = _load_progress()
    # 条目数上限：超过则拒绝新增（防匿名写盘 DoS）
    if name not in progress and len(progress) >= _MAX_PROGRESS_ENTRIES:
        return
    progress[name] = {
        "durChapterIndex": max(0, int(dur_chapter_index or 0)),
        "durChapterPos": max(0, int(dur_chapter_pos or 0)),
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


def _fix_double_encoded(text: str) -> str | None:
    """修复双重 UTF-8 编码的作者乱码。

    历史数据中作者可能被错误地"先按 latin-1 解码再按 utf-8 编码"（如
    'å\\x88\\x98æ\\x85\\x88æ¬£' 实为 '刘慈欣'）。能成功还原且含中文则返回修复值，
    否则返回 None（表示不是乱码，原样使用）。
    """
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    # 还原结果应含中文字符（作者名基本是中文）
    if re.search(r"[\u4e00-\u9fff]", repaired):
        return repaired
    return None


def save_progress_by_chapter(book_url: str, chapter: str) -> None:
    """根据章节标题或序号，将进度保存到该章节起始位置。

    chapter 支持多种格式：
    - 数字字符串（如 "5"）→ 按 1-based 序号匹配
    - 章节号（如 "第一章"）→ 按章节序号匹配
    - 标题关键词（如 "启示"）→ 模糊匹配章节标题
    - 完整标题（如 "第一章 外乡人"）→ 忽略空格模糊匹配
    """
    name = _sanitize_field(Path(book_url).stem, 200)
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
