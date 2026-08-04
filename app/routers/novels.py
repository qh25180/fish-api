"""Novel API routes."""

import html as html_mod
import json
import os
import re
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException, Query, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from urllib.parse import quote

from app.models import (
    NovelListResponse,
    ContentResponse,
    ChapterListResponse,
    DownloadRequest,
    DownloadResponse,
    UploadResponse,
)
from app.config import settings
from app.security import token_for_url, request_token_ok
from app.services import file_service, download_service

router = APIRouter(prefix="/api/v1/novels", tags=["novels"])

# Jinja2 模板：HTML 从 f-string 迁移到独立模板文件
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _check_token(request: Request = None) -> None:
    """统一验证：仅 Request 通道（Bearer/Cookie）。API_TOKEN 配置时强制。"""
    if settings.api_token and (request is None or not request_token_ok(request)):
        raise HTTPException(status_code=403, detail="无效的访问口令")


def _token_ok(request: Request = None) -> bool:
    """布尔版 token 校验（仅 Bearer/Cookie 通道）。"""
    if not settings.api_token:
        return True
    return request is not None and request_token_ok(request)


# ─── 文件列表 API ───────────────────────────────────

@router.get("", response_model=NovelListResponse)
async def list_novels(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    ext: str | None = Query(None, description="按扩展名筛选，如 .txt"),
    request: Request = None,
):
    """列出配置目录下的所有文本文件。"""
    _check_token(request)
    try:
        files, total = file_service.list_novel_files(
            page=page, page_size=page_size, ext=ext
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return NovelListResponse(
        total=total,
        page=page,
        page_size=page_size,
        novels=files,
    )


# ─── 章节 / 内容 API ───────────────────────────────

@router.get("/{filename}/chapters", response_model=ChapterListResponse)
async def get_chapters(
    filename: str,
    request: Request = None,
):
    """获取指定文件的章节列表。"""
    _check_token(request)
    try:
        chapters = file_service.get_chapters(filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ChapterListResponse(
        filename=filename,
        total_chapters=len(chapters),
        chapters=chapters,
    )


@router.get("/{filename}/chapters/{chapter_number}", response_model=ContentResponse)
async def get_chapter_content(
    filename: str,
    chapter_number: int,
    start: int = Query(
        0, ge=0, description="章节内字符偏移起始位置"
    ),
    offset: int | None = Query(
        None, ge=1, le=50000, description="限制返回字符数，不指定则返回整章"
    ),
    request: Request = None,
):
    """获取指定章节的文本内容，支持章节内偏移。"""
    _check_token(request)
    try:
        result = file_service.get_chapter_content(
            filename=filename,
            chapter_number=chapter_number,
            start=start,
            offset=offset,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ContentResponse(**result)


@router.get("/{filename}/content", response_model=ContentResponse)
async def read_content(
    filename: str,
    start: int = Query(0, ge=0, description="字符起始位置"),
    offset: int = Query(2000, ge=1, le=50000, description="返回字符数"),
    chapter: int | None = Query(
        None, ge=1, description="章节号（与 start 叠加，此时 start 为章节内偏移）"
    ),
    request: Request = None,
):
    """获取指定文件的文本内容，支持按字符偏移或章节内偏移定位。"""
    _check_token(request)
    try:
        result = file_service.get_content(
            filename=filename,
            start=start,
            offset=offset,
            chapter=chapter,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ContentResponse(**result)


# ─── 索引页 ────────────────────────────────────────

def _redirect_login() -> RedirectResponse:
    """未认证的页面请求：跳转到 /login。"""
    return RedirectResponse(url="/login", status_code=302)


_INDEX_PAGES = [
    ("[文本阅读]", "在线阅读服务器上的文本", "/api/v1/novels/read"),
    ("[书籍搜索]", "搜索并下载书籍", "/api/v1/search-page"),
    ("[文件上传]", "上传本地文件到服务器，支持分片上传", "/api/v1/novels/upload"),
    ("[远程下载]", "从 URL 拉取文件到服务器", "/api/v1/novels/download"),
    ("[文件管理]", "浏览、下载、删除服务器上的文件", "/api/v1/novels/files"),
]


@router.get("/pages", response_class=HTMLResponse, summary="索引页（浏览器访问）")
async def pages_index(
    request: Request = None,
):
    """所有页面入口的索引页。需要 token 验证（Bearer 或 Cookie）。"""
    if not _token_ok(request):
        return _redirect_login()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"pages": _INDEX_PAGES},
    )


# ─── 上传页面 ───────────────────────────────────────

@router.get("/upload", response_class=HTMLResponse, summary="上传页面（浏览器访问）")
async def upload_page(
    success: str | None = None,
    error: str | None = None,
    filename: str | None = None,
    request: Request = None,
):
    """简易文件上传页面（浏览器访问用），支持分片上传。需要 token 验证。"""
    if not _token_ok(request):
        return _redirect_login()
    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ 上传成功: {html_mod.escape(success)}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {html_mod.escape(error)}</div>'

    chunk_size = settings.upload_chunk_size_kb * 1024

    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "token": quote(token_for_url(request), safe=""),
            "chunk_size": chunk_size,
            "file_exts": ", ".join(settings.text_file_extensions_list),
            "msg_html": msg_html,
        },
    )


# ─── 文件上传（单次） ───────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    request: Request = None,
):
    """上传本地文件到服务器配置目录（单次请求，兼容旧版 API）。

    需要配置 UPLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需在表单中传入一致的 token。
    浏览器上传成功后自动重定向回上传页面并显示结果。
    """
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    if not settings.upload_enabled:
        err_msg = "上传功能未启用（UPLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    if not _token_ok(request):
        err_msg = "无效的访问口令"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    if not file.filename:
        err_msg = "未选择文件"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    safe_name = os.path.basename(file.filename)
    safe_name = download_service._ensure_allowed_extension(safe_name)

    novels_dir = settings.text_files_dir
    novels_dir.mkdir(parents=True, exist_ok=True)
    save_path, renamed = await download_service._generate_unique_filename(
        novels_dir, safe_name
    )

    max_size = settings.max_file_size_mb * 1024 * 1024
    file_size = 0
    try:
        async with aiofiles.open(save_path, "wb") as f:
            while chunk := await file.read(65536):
                file_size += len(chunk)
                if file_size > max_size:
                    await f.close()
                    save_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"文件超过大小限制 {settings.max_file_size_mb}MB"
                    )
                await f.write(chunk)
    except ValueError:
        raise
    except Exception as e:
        save_path.unlink(missing_ok=True)
        err_msg = f"文件写入失败: {e}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=500, detail=err_msg)

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/upload?success={quote(save_path.name)}",
            status_code=303,
        )

    return UploadResponse(
        filename=save_path.name,
        save_path=str(save_path),
        file_size=file_size,
        renamed=renamed,
    )


# ─── 分片上传 ───────────────────────────────────────

def _upload_tmp_dir() -> Path:
    """获取分片上传临时目录。"""
    d = settings.text_files_dir / ".upload_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_stale_uploads():
    """清理超过 1 小时的过期分片上传。"""
    tmp = _upload_tmp_dir()
    now = time.time()
    for entry in tmp.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            shutil.rmtree(entry, ignore_errors=True)
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            created = meta.get("created_at", 0)
            if now - created > 3600:
                shutil.rmtree(entry, ignore_errors=True)
        except Exception:
            shutil.rmtree(entry, ignore_errors=True)


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _safe_upload_id(upload_id: str) -> str:
    """校验 upload_id 为合法 UUID，防路径穿越。非法抛 400。"""
    if not upload_id or not _UUID_RE.fullmatch(upload_id):
        raise HTTPException(status_code=400, detail="无效的上传会话 ID")
    return upload_id


@router.post("/upload/init")
async def upload_init(
    filename: str = Form(...),
    total_size: int = Form(...),
    total_chunks: int = Form(...),
    request: Request = None,
):
    """初始化分片上传，返回 upload_id 和已上传分片列表（支持断点续传）。"""
    if not settings.upload_enabled:
        raise HTTPException(status_code=403, detail="上传功能未启用（UPLOAD_ENABLED=false）")

    _check_token(request)

    if total_size > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件超过大小限制 {settings.max_file_size_mb}MB")

    if total_chunks < 1:
        raise HTTPException(status_code=400, detail="分片数不能小于 1")

    _cleanup_stale_uploads()

    upload_id = str(uuid.uuid4())
    upload_dir = _upload_tmp_dir() / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "filename": os.path.basename(filename),
        "total_size": total_size,
        "total_chunks": total_chunks,
        "created_at": time.time(),
    }
    (upload_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    return {"upload_id": upload_id, "uploaded_chunks": []}


@router.post("/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    request: Request = None,
):
    """上传单个分片。需要 token 验证。"""
    _check_token(request)
    _safe_upload_id(upload_id)
    upload_dir = _upload_tmp_dir() / upload_id
    meta_path = upload_dir / "meta.json"

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    if chunk_index < 0 or chunk_index >= meta["total_chunks"]:
        raise HTTPException(status_code=400, detail=f"分片序号无效，有效范围: 0-{meta['total_chunks']-1}")

    chunk_path = upload_dir / f"chunk_{chunk_index}"
    async with aiofiles.open(chunk_path, "wb") as f:
        while data := await chunk.read(65536):
            await f.write(data)

    return {"success": True, "chunk_index": chunk_index}


@router.post("/upload/complete", response_model=UploadResponse)
async def upload_complete(
    upload_id: str = Form(...),
    request: Request = None,
):
    """合并所有分片为最终文件。"""
    _check_token(request)
    _safe_upload_id(upload_id)

    upload_dir = _upload_tmp_dir() / upload_id
    meta_path = upload_dir / "meta.json"

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    total_chunks = meta["total_chunks"]

    missing = [i for i in range(total_chunks) if not (upload_dir / f"chunk_{i}").exists()]
    if missing:
        raise HTTPException(status_code=400, detail=f"分片不完整，缺少: {missing}")

    safe_name = download_service._ensure_allowed_extension(meta["filename"])

    novels_dir = settings.text_files_dir
    novels_dir.mkdir(parents=True, exist_ok=True)
    save_path, renamed = await download_service._generate_unique_filename(novels_dir, safe_name)

    try:
        async with aiofiles.open(save_path, "wb") as out:
            for i in range(total_chunks):
                chunk_path = upload_dir / f"chunk_{i}"
                async with aiofiles.open(chunk_path, "rb") as cf:
                    while data := await cf.read(65536):
                        await out.write(data)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"文件合并失败: {e}")

    file_size = save_path.stat().st_size

    shutil.rmtree(upload_dir, ignore_errors=True)

    return UploadResponse(
        filename=save_path.name,
        save_path=str(save_path),
        file_size=file_size,
        renamed=renamed,
    )


@router.delete("/upload/cancel")
async def upload_cancel(
    upload_id: str = Form(...),
    request: Request = None,
):
    """取消分片上传并清理临时文件。需要 token 验证。"""
    _check_token(request)
    _safe_upload_id(upload_id)
    upload_dir = _upload_tmp_dir() / upload_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
    return {"success": True}


# ─── 文件管理页面 ───────────────────────────────────

def _format_file_size(size_bytes: int) -> str:
    """将字节数格式化为可读字符串。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


@router.get("/files", response_class=HTMLResponse, summary="文件管理页面（浏览器访问）")
async def files_page(
    page: int = Query(1, ge=1),
    success: str | None = None,
    error: str | None = None,
    request: Request = None,
):
    """文件管理页面：分页浏览、下载、删除服务器上的文件。需要 token 验证（Bearer 或 Cookie）。"""
    from pathlib import Path
    if not _token_ok(request):
        return _redirect_login()

    page_size = 20
    try:
        files, total = file_service.list_novel_files(page=page, page_size=page_size)
    except Exception as e:
        files, total = [], 0
        error = str(e)

    total_pages = max(1, (total + page_size - 1) // page_size)

    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ {html_mod.escape(success)}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {html_mod.escape(error)}</div>'

    hidden_books = _load_hidden_books()
    row_list = []
    for f in files:
        safe_fn = html_mod.escape(f.filename)
        encoded_fn = quote(f.filename, safe="")
        book_name = Path(f.filename).stem
        is_hidden = book_name in hidden_books
        row_list.append({
            "safe_fn": safe_fn,
            "encoded_fn": encoded_fn,
            "dl_url": f"/api/v1/novels/{encoded_fn}/download",
            "size_hint": _format_file_size(f.file_size),
            "author": html_mod.escape(f.author),
            "mod_time": f.modified_time.strftime("%Y-%m-%d %H:%M"),
            "is_hidden": is_hidden,
            "hide_btn_text": "显示" if is_hidden else "隐藏",
            "hide_btn_class": "btn-unhide" if is_hidden else "btn-hide",
        })

    pagination_html = ""
    if total_pages > 1:
        pagination_html = '<div class="pagination">'
        if page > 1:
            pagination_html += f'<a href="?page={page - 1}">上一页</a>'
        pagination_html += f'<span>第 {page} / {total_pages} 页（共 {total} 个文件）</span>'
        if page < total_pages:
            pagination_html += f'<a href="?page={page + 1}">下一页</a>'
        pagination_html += '</div>'
    elif total > 0:
        pagination_html = f'<div class="pagination"><span>共 {total} 个文件</span></div>'

    return templates.TemplateResponse(
        request=request,
        name="files.html",
        context={
            "msg_html": msg_html,
            "files": row_list,
            "pagination_html": pagination_html,
        },
    )


# ─── 文件删除 ───────────────────────────────────────

@router.post("/{filename}/delete")
async def delete_file(
    filename: str,
    request: Request = None,
):
    """删除服务器上的文件。

    需要配置 FILE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需传入一致的 token。
    浏览器请求成功后重定向回文件管理页面。
    """
    accept = request.headers.get("accept", "") if request else "" if request else ""
    is_browser = "text/html" in accept

    if not settings.file_download_enabled:
        err_msg = "文件下载功能未启用（FILE_DOWNLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    if not _token_ok(request):
        err_msg = "无效的访问口令"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    try:
        file_path = file_service._safe_path(filename)
    except ValueError as e:
        err_msg = str(e)
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    if not file_path.exists():
        err_msg = "文件不存在"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=404, detail=err_msg)

    if not file_path.is_file():
        err_msg = "无效的文件"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    try:
        file_path.unlink()
    except Exception as e:
        err_msg = f"删除失败: {e}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=500, detail=err_msg)

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/files?success={quote(f'已删除: {filename}')}",
            status_code=303,
        )

    return {"success": True, "filename": filename}


# ─── 文件隐藏/显示 ──────────────────────────────────

def _hidden_books_file():
    from pathlib import Path
    return settings.text_files_dir / ".hidden_books.json"


def _load_hidden_books() -> set:
    import json
    path = _hidden_books_file()
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_hidden_books(hidden: set):
    import json
    path = _hidden_books_file()
    path.write_text(json.dumps(list(hidden), ensure_ascii=False), encoding="utf-8")


@router.post("/{filename}/hide")
async def hide_book(
    filename: str,
    request: Request = None,
):
    """隐藏/显示书籍（从阅读器隐藏）。"""
    accept = request.headers.get("accept", "") if request else "" if request else ""
    is_browser = "text/html" in accept

    if not _token_ok(request):
        err_msg = "无效的访问口令"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    hidden = _load_hidden_books()
    name = Path(filename).stem

    if name in hidden:
        hidden.discard(name)
        msg = f"已显示: {filename}"
    else:
        hidden.add(name)
        msg = f"已隐藏: {filename}"

    _save_hidden_books(hidden)

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/files?success={quote(msg)}",
            status_code=303,
        )

    return {"success": True, "filename": filename, "hidden": name in hidden}


# ─── 文件重命名 ─────────────────────────────────────

@router.post("/{filename}/rename")
async def rename_book(
    filename: str,
    new_name: str = Form(...),
    request: Request = None,
):
    """重命名书籍文件，同步更新进度文件。"""
    accept = request.headers.get("accept", "") if request else "" if request else ""
    is_browser = "text/html" in accept

    if not _token_ok(request):
        err_msg = "无效的访问口令"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    # 安全校验
    try:
        old_path = file_service._safe_path(filename)
    except ValueError as e:
        err_msg = str(e)
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    if not old_path.exists():
        err_msg = "文件不存在"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=404, detail=err_msg)

    # 构建新文件名
    old_stem = Path(filename).stem
    suffix = old_path.suffix
    safe_new_name = os.path.basename(new_name.strip())
    if not safe_new_name:
        err_msg = "新名称不能为空"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    # 确保新文件名有扩展名
    if not Path(safe_new_name).suffix:
        safe_new_name += suffix

    new_path = old_path.parent / safe_new_name

    if new_path.exists() and new_path != old_path:
        err_msg = f"文件名已存在: {safe_new_name}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    try:
        old_path.rename(new_path)
    except Exception as e:
        err_msg = f"重命名失败: {e}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=500, detail=err_msg)

    # 同步更新进度文件
    new_stem = Path(safe_new_name).stem
    progress_path = settings.text_files_dir / ".legado_progress.json"
    if progress_path.exists():
        try:
            import json
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            if old_stem in progress:
                progress[new_stem] = progress.pop(old_stem)
                progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # 同步更新隐藏列表
    hidden_path = settings.text_files_dir / ".hidden_books.json"
    if hidden_path.exists():
        try:
            import json
            hidden = set(json.loads(hidden_path.read_text(encoding="utf-8")))
            if old_stem in hidden:
                hidden.discard(old_stem)
                hidden.add(new_stem)
                hidden_path.write_text(json.dumps(list(hidden), ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # 清除章节缓存
    from app.services.file_service import _read_and_parse_cached
    _read_and_parse_cached.cache_clear()

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/files?success={quote(f'已重命名: {filename} → {safe_new_name}')}",
            status_code=303,
        )

    return {"success": True, "old_filename": filename, "new_filename": safe_new_name}


# ─── 一键批量重命名（按 FILE_RENAME_MODE 配置） ──────

@router.post("/batch-rename")
async def batch_rename_files(
    request: Request = None,
):
    """按当前重命名模式一键重命名所有未隐藏的小说文件。"""
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    if not _token_ok(request):
        err_msg = "无效的访问口令"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    import json
    from app.utils.pinyin_util import build_rename_name
    from app.services.file_service import _read_and_parse_cached

    novels_dir = settings.text_files_dir
    hidden = _load_hidden_books()

    # 读取进度文件（用于同步 key）
    progress_path = novels_dir / ".legado_progress.json"
    progress = {}
    if progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            progress = progress if isinstance(progress, dict) else {}
        except Exception:
            progress = {}

    renamed: list[str] = []
    errors: list[str] = []
    skipped = 0

    for f in sorted(novels_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in settings.text_file_extensions_list:
            continue
        if f.stem in hidden:
            continue  # 跳过隐藏书籍

        new_name = build_rename_name(f.name)
        if new_name == f.name:
            skipped += 1
            continue

        # 冲突处理：目标已存在则加 (1)、(2)…
        target = f.parent / new_name
        counter = 1
        while target.exists() and target != f:
            target = f.parent / f"{Path(new_name).stem} ({counter}){Path(new_name).suffix}"
            counter += 1

        try:
            f.rename(target)
        except Exception as e:
            errors.append(f"{f.name}: {e}")
            continue

        # 同步进度文件 key
        if f.stem in progress:
            progress[target.stem] = progress.pop(f.stem)
        renamed.append(f"{f.name} → {target.name}")

    # 写回进度文件（有重命名或文件存在时）
    if renamed or progress_path.exists():
        try:
            novels_dir.mkdir(parents=True, exist_ok=True)
            tmp = progress_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(progress_path)
        except Exception:
            pass

    # 清除章节缓存
    _read_and_parse_cached.cache_clear()

    msg = f"重命名完成：{len(renamed)} 个文件，跳过 {skipped} 个"
    if errors:
        msg += f"，失败 {len(errors)} 个（{'；'.join(errors[:3])}）"

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/files?success={quote(msg)}",
            status_code=303,
        )

    return {"success": True, "renamed": renamed, "skipped": skipped, "errors": errors}


# ─── 修改作者 ───────────────────────────────────────

@router.post("/{filename}/author")
async def update_author(
    filename: str,
    new_author: str = Form(...),
    request: Request = None,
):
    """修改文件的作者信息。"""
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    if not _token_ok(request):
        err_msg = "无效的访问口令"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    from pathlib import Path
    stem = Path(filename).stem
    progress_path = settings.text_files_dir / ".legado_progress.json"
    try:
        import json
        progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
        if stem not in progress:
            progress[stem] = {}
        progress[stem]["author"] = new_author.strip()
        tmp_path = progress_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(progress_path)
    except Exception as e:
        err_msg = f"保存作者信息失败: {e}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=500, detail=err_msg)

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/files?success={quote(f'已更新作者: {filename} → {new_author}')}",
            status_code=303,
        )

    return {"success": True, "filename": filename, "author": new_author.strip()}


# ─── 远程下载页面 ───────────────────────────────────

@router.get("/download", response_class=HTMLResponse, summary="远程下载页面（浏览器访问）")
async def download_page(
    success: str | None = None,
    error: str | None = None,
    request: Request = None,
):
    """简易远程下载页面（浏览器访问用）。需要 token 验证（Bearer 或 Cookie）。"""
    if not _token_ok(request):
        return _redirect_login()
    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ 下载成功: {html_mod.escape(success)}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {html_mod.escape(error)}</div>'

    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={"msg_html": msg_html},
    )


# ─── 远程下载 ───────────────────────────────────────

@router.post("/download", response_model=DownloadResponse)
async def download_novel(
    url: str | None = Form(None),
    request: Request = None,
    body: DownloadRequest | None = None,
):
    """从 URL 下载文件到配置目录（自动防同名覆盖）。

    需要配置 REMOTE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需传入一致的 token。
    浏览器下载成功后自动重定向回下载页面并显示结果。
    """
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    if url is None and body is not None:
        url = body.url
        token = token or body.token

    if not settings.remote_download_enabled:
        err_msg = "远程下载功能未启用（REMOTE_DOWNLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/download?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    if not _token_ok(request):
        err_msg = "无效的访问口令"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/download?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    if not url:
        err_msg = "请输入下载链接"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/download?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    url = url.strip()

    if not url.startswith(("http://", "https://")):
        err_msg = "仅支持 http:// 和 https:// 协议的 URL"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/download?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    try:
        result = await download_service.download_novel(url)
    except ValueError as e:
        err_msg = str(e)
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/download?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)
    except Exception as e:
        err_msg = str(e)
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/download?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=500, detail=err_msg)

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/download?success={quote(result['filename'])}",
            status_code=303,
        )

    return DownloadResponse(**result)


# ─── 文件下载（将服务器文件返回给客户端）────────────

@router.get("/{filename:path}/download")
async def download_file(
    filename: str,
    request: Request = None,
):
    """下载服务器上的文件到本地（浏览器/curl 直接访问）。

    需要配置 FILE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需传入一致的 token（Bearer 或 Cookie）。
    """
    if not settings.file_download_enabled:
        raise HTTPException(
            status_code=403,
            detail="文件下载未启用（FILE_DOWNLOAD_ENABLED=false）",
        )

    _check_token(request)

    try:
        file_path = file_service._safe_path(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="无效的文件")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )


# ─── 文本阅读器页面 ─────────────────────────────────

@router.get("/read", response_class=HTMLResponse, summary="文本阅读器（浏览器访问）")
async def read_page(
    request: Request = None,
):
    """在线阅读服务器上的文本。需要 token 验证（Bearer 或 Cookie）。"""
    if not _token_ok(request):
        return _redirect_login()

    return templates.TemplateResponse(
        request=request,
        name="reader.html",
        context={"token": quote(token_for_url(request), safe="")},
    )
