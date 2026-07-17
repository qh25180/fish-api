"""Legado HTTP API 兼容路由。

提供 Dicarbene/yuedu_vscode_dicarbene 插件所需的端点。
所有响应均包装在 LegadoApiResponse 统一格式中。
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.legado_models import (
    LegadoApiResponse,
    LegadoBook,
    LegadoChapter,
    LegadoBookProgress,
    LegadoChapterProgress,
)
from app.services import legado_service

router = APIRouter(tags=["legado"])


def ok(data):
    """构建成功响应。"""
    return LegadoApiResponse(isSuccess=True, errorMsg="", data=data)


def fail(message: str, status_code: int = 400):
    """构建失败响应并抛出 HTTP 异常。"""
    detail = LegadoApiResponse(
        isSuccess=False, errorMsg=message, data=None
    ).model_dump()
    raise HTTPException(status_code=status_code, detail=detail)


@router.get("/getBookshelf")
async def get_bookshelf():
    """获取书架列表（本地文件列表 → Legado Book 格式）。"""
    try:
        books = legado_service.get_bookshelf()
        return ok(books)
    except Exception as e:
        return fail(str(e), 500)


@router.get("/getChapterList")
async def get_chapter_list(url: str = Query(..., description="文件标识(bookUrl)")):
    """获取指定文件的章节目录。"""
    try:
        chapters = legado_service.get_chapter_list(url)
        return ok(chapters)
    except FileNotFoundError as e:
        return fail(str(e), 404)
    except Exception as e:
        return fail(str(e), 500)


@router.get("/getBookContent")
async def get_book_content(
    url: str = Query(..., description="文件标识(bookUrl)"),
    index: int = Query(..., ge=0, description="章节索引(从0开始)"),
):
    """获取指定章节的完整文本内容。"""
    try:
        content = legado_service.get_book_content(url, index)
        return ok(content)
    except FileNotFoundError as e:
        return fail(str(e), 404)
    except ValueError as e:
        return fail(str(e), 400)
    except Exception as e:
        return fail(str(e), 500)


@router.post("/saveBookProgressByChapter")
async def save_book_progress_by_chapter(progress: LegadoChapterProgress):
    """按章节标题或序号切换阅读进度（保存到该章节起始位置）。"""
    try:
        legado_service.save_progress_by_chapter(
            book_url=progress.bookUrl,
            chapter=progress.chapter,
        )
        return ok("进度已保存")
    except FileNotFoundError as e:
        return fail(str(e), 404)
    except ValueError as e:
        return fail(str(e), 400)
    except Exception as e:
        return fail(str(e), 500)


@router.post("/saveBookProgress")
async def save_book_progress(progress: LegadoBookProgress):
    """保存阅读进度（持久化到 JSON 文件）。"""
    try:
        legado_service.save_book_progress(
            name=progress.name,
            author=progress.author,
            dur_chapter_index=progress.durChapterIndex,
            dur_chapter_pos=progress.durChapterPos,
            dur_chapter_title=progress.durChapterTitle,
            dur_chapter_time=progress.durChapterTime,
        )
        return ok("进度已保存")
    except Exception as e:
        return fail(str(e), 500)
