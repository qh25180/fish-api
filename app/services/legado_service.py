"""Legado 映射服务：将 QHAPI 内部数据模型转为 Legado 兼容格式。"""

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


def get_bookshelf() -> list[LegadoBook]:
    """获取书架列表（所有文本文件 → LegadoBook 列表）。"""
    files, _ = list_novel_files(page=1, page_size=9999)
    return [_file_to_legado_book(f.filename, f.estimated_chapters) for f in files]


def _file_to_legado_book(filename: str, total_chapters: int) -> LegadoBook:
    """将单个文件转为 LegadoBook。"""
    name = Path(filename).stem
    # 尝试读取第一章标题作为 durChapterTitle
    try:
        chapters = qhapi_get_chapters(filename)
        first_chapter_title = chapters[0].title if chapters else ""
    except Exception:
        first_chapter_title = ""

    return LegadoBook(
        name=name,
        author="未知作者",
        bookUrl=filename,
        totalChapterNum=total_chapters,
        durChapterTitle=first_chapter_title,
        durChapterIndex=0,
        durChapterPos=0,
    )


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


def get_book_content(book_url: str, chapter_index: int) -> str:
    """获取指定章节的完整文本内容（不截断）。

    返回纯文本字符串，插件会自己按 snippetLength 截断。
    """
    # 获取该章节的完整内容（不指定 offset，返回整章）
    result = get_content(
        filename=book_url,
        start=0,
        offset=999999999,
        chapter=chapter_index + 1,
    )
    return result["content"]


def save_book_progress(
    name: str,
    author: str,
    dur_chapter_index: int,
    dur_chapter_pos: int,
    dur_chapter_title: str = "",
) -> None:
    """保存阅读进度。

    当前以日志形式记录，后续可扩展为持久化存储。
    因为 QHAPI 的文件在服务器本地，写回进度可用于下次继续阅读。
    """
    import datetime
    now = datetime.datetime.now().isoformat()
    print(f"[Legado Progress] {now} | {name}({author}) "
          f"→ 章节 {dur_chapter_index + 1} 位置 {dur_chapter_pos}")
