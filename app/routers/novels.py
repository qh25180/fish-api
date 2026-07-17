"""Novel API routes."""

import os
import secrets

import aiofiles
from fastapi import APIRouter, HTTPException, Query, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
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
from app.services import file_service, download_service

router = APIRouter(prefix="/api/v1/novels", tags=["novels"])


@router.get("", response_model=NovelListResponse)
async def list_novels(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    ext: str | None = Query(None, description="按扩展名筛选，如 .txt"),
):
    """列出配置目录下的所有文本文件。"""
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


@router.get("/{filename}/chapters", response_model=ChapterListResponse)
async def get_chapters(filename: str):
    """获取指定文件的章节列表。"""
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
):
    """获取指定章节的文本内容，支持章节内偏移。"""
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
):
    """获取指定文件的文本内容，支持按字符偏移或章节内偏移定位。"""
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


# ─── 上传页面 ───────────────────────────────────────

@router.get("/upload", response_class=HTMLResponse, summary="上传页面（浏览器访问）")
async def upload_page(
    success: str | None = None,
    error: str | None = None,
    filename: str | None = None,
):
    """简易文件上传页面（浏览器访问用）。"""
    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ 上传成功: {success}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {error}</div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>文件上传</title>
<style>
  body {{ font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
  form {{ border: 1px solid #ddd; padding: 24px; border-radius: 8px; background: #fafafa; }}
  label {{ display: block; margin: 12px 0 4px; font-weight: bold; }}
  input[type=file], input[type=text] {{ width: 100%; padding: 8px; box-sizing: border-box; }}
  button {{ margin-top: 16px; padding: 10px 24px; background: #007acc; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }}
  button:hover {{ background: #005999; }}
  .tip {{ color: #666; font-size: 14px; margin-top: 8px; }}
  .msg {{ padding: 12px; border-radius: 4px; margin-bottom: 16px; }}
  .msg.success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
  .msg.error {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
</style>
</head>
<body>
<h2>📤 文件上传</h2>
{msg_html}
<form action="/api/v1/novels/upload" method="post" enctype="multipart/form-data">
  <label for="file">选择文件</label>
  <input type="file" name="file" id="file" required>
  <label for="token">访问口令</label>
  <input type="text" name="token" id="token" placeholder="如需口令请在此输入">
  <button type="submit">上传</button>
  <div class="tip">支持的文件类型: {', '.join(settings.text_file_extensions_list)}</div>
</form>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── 文件上传 ───────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    token: str | None = Form(None),
    request: Request = None,
):
    """上传本地文件到服务器配置目录。

    需要配置 UPLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需在表单中传入一致的 token。
    浏览器上传成功后自动重定向回上传页面并显示结果。
    """
    # 判断是否为浏览器请求
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    # 开关检查
    if not settings.upload_enabled:
        err_msg = "上传功能未启用（UPLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    # Token 验证（配置为空字符串则跳过）
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            err_msg = "无效的访问口令"
            if is_browser:
                return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
            raise HTTPException(status_code=403, detail=err_msg)

    if not file.filename:
        err_msg = "未选择文件"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    # 安全处理文件名
    safe_name = os.path.basename(file.filename)
    safe_name = download_service._ensure_allowed_extension(safe_name)

    # 防同名覆盖
    novels_dir = settings.text_files_dir
    novels_dir.mkdir(parents=True, exist_ok=True)
    save_path, renamed = await download_service._generate_unique_filename(
        novels_dir, safe_name
    )

    # 流式写入 + 大小限制
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

    # 浏览器请求 → 重定向回上传页面显示成功
    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/upload?success={quote(save_path.name)}",
            status_code=303,
        )

    # API 请求 → 返回 JSON
    return UploadResponse(
        filename=save_path.name,
        save_path=str(save_path),
        file_size=file_size,
        renamed=renamed,
    )


@router.post("/download", response_model=DownloadResponse)
async def download_novel(request: DownloadRequest):
    """从 URL 下载文件到配置目录（自动防同名覆盖）。

    需要配置 REMOTE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需在请求体中传入一致的 token。
    """
    # 开关检查
    if not settings.remote_download_enabled:
        raise HTTPException(
            status_code=403,
            detail="远程下载功能未启用（REMOTE_DOWNLOAD_ENABLED=false）",
        )

    # Token 验证（配置为空字符串则跳过）
    if settings.api_token:
        token = request.token or ""
        if not secrets.compare_digest(token, settings.api_token):
            raise HTTPException(
                status_code=403,
                detail="无效的访问口令",
            )

    url = request.url.strip()

    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400, detail="仅支持 http:// 和 https:// 协议的 URL"
        )

    try:
        result = await download_service.download_novel(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return DownloadResponse(**result)


# ─── 文件下载（将服务器文件返回给客户端）────────────

@router.get("/{filename:path}/download")
async def download_file(
    filename: str,
    token: str | None = Query(None, description="访问口令"),
):
    """下载服务器上的文件到本地（浏览器/curl 直接访问）。

    需要配置 FILE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需在查询参数中传入一致的 token。
    """
    # 开关检查
    if not settings.file_download_enabled:
        raise HTTPException(
            status_code=403,
            detail="文件下载未启用（FILE_DOWNLOAD_ENABLED=false）",
        )

    # Token 验证（配置为空字符串则跳过）
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            raise HTTPException(
                status_code=403,
                detail="无效的访问口令",
            )

    # 安全路径校验
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
