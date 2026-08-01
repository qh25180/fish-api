"""Legado HTTP API 兼容路由。

提供 Dicarbene/yuedu_vscode_dicarbene 插件所需的端点。
所有响应均包装在 LegadoApiResponse 统一格式中。

安全说明：Legado 为外部协议（Legado App / VS Code 插件 / 脚本），
**永不验证 token**，只受 settings.legado_enabled 开关控制（默认开启）。
"""

import secrets

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.legado_models import (
    LegadoApiResponse,
    LegadoBook,
    LegadoChapter,
    LegadoBookProgress,
    LegadoChapterProgress,
)
from app.services import legado_service

router = APIRouter(tags=["legado"])


def _require_legado_enabled():
    """若 Legado 开关关闭，返回 LegadoApiResponse 格式的 403。"""
    if not settings.legado_enabled:
        detail = LegadoApiResponse(
            isSuccess=False, errorMsg="Legado API 未开放", data=None
        ).model_dump()
        raise HTTPException(status_code=403, detail=detail)


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
async def get_bookshelf(
    token: str | None = Query(None),
    page: int = Query(1, ge=1, description="页码（可选分页）"),
    page_size: int = Query(0, ge=0, description="每页数量，0 表示全量返回"),
):
    """获取书架列表（本地文件列表 → Legado Book 格式）。

    可选分页：page + page_size（page_size=0 时全量返回，兼容插件调用）。
    """
    _require_legado_enabled()
    try:
        books = legado_service.get_bookshelf(page=page, page_size=page_size)
        return ok(books)
    except Exception as e:
        return fail(str(e), 500)


@router.get("/getChapterList")
async def get_chapter_list(
    url: str = Query(..., description="文件标识(bookUrl)"),
    token: str | None = Query(None),
):
    """获取指定文件的章节目录。"""
    _require_legado_enabled()
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
    token: str | None = Query(None),
):
    """获取指定章节的完整文本内容。"""
    _require_legado_enabled()
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
async def save_book_progress_by_chapter(
    progress: LegadoChapterProgress,
    token: str | None = Query(None),
):
    """按章节标题或序号切换阅读进度（保存到该章节起始位置）。"""
    _require_legado_enabled()
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
async def save_book_progress(
    progress: LegadoBookProgress,
    token: str | None = Query(None),
):
    """保存阅读进度（持久化到 JSON 文件）。"""
    _require_legado_enabled()
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
