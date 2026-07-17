"""Novel API routes."""

import html as html_mod
import json
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    """简易文件上传页面（浏览器访问用），支持分片上传。"""
    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ 上传成功: {html_mod.escape(success)}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {html_mod.escape(error)}</div>'

    chunk_size = settings.upload_chunk_size_kb * 1024

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
  button:disabled {{ background: #999; cursor: not-allowed; }}
  .tip {{ color: #666; font-size: 14px; margin-top: 8px; }}
  .msg {{ padding: 12px; border-radius: 4px; margin-bottom: 16px; }}
  .msg.success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
  .msg.error {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
  .file-info {{ background: #e9ecef; padding: 10px; border-radius: 4px; margin: 8px 0; font-size: 14px; display: none; }}
  .progress-wrap {{ display: none; margin-top: 12px; }}
  .progress-bar {{ width: 100%; height: 20px; background: #e9ecef; border-radius: 4px; overflow: hidden; }}
  .progress-fill {{ height: 100%; background: #28a745; width: 0%; transition: width 0.3s; }}
  .progress-text {{ font-size: 13px; color: #666; margin-top: 4px; }}
  .status {{ margin-top: 8px; font-size: 14px; }}
</style>
</head>
<body>
<h2>📤 文件上传</h2>
{msg_html}
<form id="uploadForm">
  <label for="file">选择文件</label>
  <input type="file" name="file" id="file" required>
  <div class="file-info" id="fileInfo"></div>
  <label for="token">访问口令</label>
  <input type="text" name="token" id="token" placeholder="如需口令请在此输入">
  <div class="progress-wrap" id="progressWrap">
    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
    <div class="progress-text" id="progressText"></div>
  </div>
  <div class="status" id="status"></div>
  <button type="submit" id="submitBtn">上传</button>
  <div class="tip">支持的文件类型: {', '.join(settings.text_file_extensions_list)}</div>
</form>
<script>
(function() {{
  const CHUNK_SIZE = {chunk_size};
  const form = document.getElementById('uploadForm');
  const fileInput = document.getElementById('file');
  const fileInfo = document.getElementById('fileInfo');
  const progressWrap = document.getElementById('progressWrap');
  const progressFill = document.getElementById('progressFill');
  const progressText = document.getElementById('progressText');
  const status = document.getElementById('status');
  const submitBtn = document.getElementById('submitBtn');

  function formatSize(bytes) {{
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }}

  fileInput.addEventListener('change', function() {{
    const f = this.files[0];
    if (!f) {{ fileInfo.style.display = 'none'; return; }}
    const totalChunks = Math.ceil(f.size / CHUNK_SIZE);
    fileInfo.style.display = 'block';
    fileInfo.innerHTML = '<b>' + f.name + '</b><br>大小: ' + formatSize(f.size) + ' | 分片: ' + totalChunks + ' × ' + formatSize(CHUNK_SIZE);
  }});

  form.addEventListener('submit', async function(e) {{
    e.preventDefault();
    const f = fileInput.files[0];
    if (!f) {{ status.innerHTML = '<span style="color:red">请先选择文件</span>'; return; }}

    const token = document.getElementById('token').value.trim();
    const totalChunks = Math.ceil(f.size / CHUNK_SIZE);
    submitBtn.disabled = true;
    progressWrap.style.display = 'block';
    status.innerHTML = '正在初始化...';

    try {{
      // 1. 初始化
      const initData = new FormData();
      initData.append('filename', f.name);
      initData.append('total_size', f.size);
      initData.append('total_chunks', totalChunks);
      if (token) initData.append('token', token);

      const initResp = await fetch('/api/v1/novels/upload/init', {{ method: 'POST', body: initData }});
      if (!initResp.ok) {{
        const err = await initResp.json();
        throw new Error(err.detail || '初始化失败');
      }}
      const init = await initResp.json();
      const uploadId = init.upload_id;
      const uploaded = new Set(init.uploaded_chunks || []);

      // 2. 上传分片
      let done = uploaded.size;
      progressFill.style.width = (done / totalChunks * 100) + '%';
      progressText.textContent = done + ' / ' + totalChunks + ' 片已完成';
      status.innerHTML = '正在上传分片...';

      for (let i = 0; i < totalChunks; i++) {{
        if (uploaded.has(i)) continue;
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, f.size);
        const chunk = f.slice(start, end);

        const chunkData = new FormData();
        chunkData.append('upload_id', uploadId);
        chunkData.append('chunk_index', i);
        chunkData.append('chunk', chunk, 'chunk');

        const chunkResp = await fetch('/api/v1/novels/upload/chunk', {{ method: 'POST', body: chunkData }});
        if (!chunkResp.ok) {{
          const err = await chunkResp.json();
          throw new Error(err.detail || '分片 ' + i + ' 上传失败');
        }}
        done++;
        progressFill.style.width = (done / totalChunks * 100) + '%';
        progressText.textContent = done + ' / ' + totalChunks + ' 片已完成';
      }}

      // 3. 合并
      status.innerHTML = '正在合并文件...';
      const completeData = new FormData();
      completeData.append('upload_id', uploadId);
      if (token) completeData.append('token', token);

      const completeResp = await fetch('/api/v1/novels/upload/complete', {{ method: 'POST', body: completeData }});
      if (!completeResp.ok) {{
        const err = await completeResp.json();
        throw new Error(err.detail || '合并失败');
      }}

      // 成功 → 跳转回页面
      const result = await completeResp.json();
      window.location.href = '/api/v1/novels/upload?success=' + encodeURIComponent(result.filename);
    }} catch (err) {{
      status.innerHTML = '<span style="color:red">❌ ' + err.message + '</span>';
      submitBtn.disabled = false;
    }}
  }});
}})();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── 文件上传（单次） ───────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    token: str | None = Form(None),
    request: Request = None,
):
    """上传本地文件到服务器配置目录（单次请求，兼容旧版 API）。

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


@router.post("/upload/init")
async def upload_init(
    filename: str = Form(...),
    total_size: int = Form(...),
    total_chunks: int = Form(...),
    token: str | None = Form(None),
):
    """初始化分片上传，返回 upload_id 和已上传分片列表（支持断点续传）。"""
    if not settings.upload_enabled:
        raise HTTPException(status_code=403, detail="上传功能未启用（UPLOAD_ENABLED=false）")

    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            raise HTTPException(status_code=403, detail="无效的访问口令")

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
):
    """上传单个分片。"""
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
    token: str | None = Form(None),
):
    """合并所有分片为最终文件。"""
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            raise HTTPException(status_code=403, detail="无效的访问口令")

    upload_dir = _upload_tmp_dir() / upload_id
    meta_path = upload_dir / "meta.json"

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    total_chunks = meta["total_chunks"]

    # 检查分片是否齐全
    missing = [i for i in range(total_chunks) if not (upload_dir / f"chunk_{i}").exists()]
    if missing:
        raise HTTPException(status_code=400, detail=f"分片不完整，缺少: {missing}")

    # 安全处理文件名
    safe_name = download_service._ensure_allowed_extension(meta["filename"])

    # 防同名覆盖
    novels_dir = settings.text_files_dir
    novels_dir.mkdir(parents=True, exist_ok=True)
    save_path, renamed = await download_service._generate_unique_filename(novels_dir, safe_name)

    # 按顺序拼接分片
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

    # 清理临时目录
    shutil.rmtree(upload_dir, ignore_errors=True)

    return UploadResponse(
        filename=save_path.name,
        save_path=str(save_path),
        file_size=file_size,
        renamed=renamed,
    )


@router.delete("/upload/cancel")
async def upload_cancel(upload_id: str = Form(...)):
    """取消分片上传并清理临时文件。"""
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
    token: str | None = Query(None),
    page: int = Query(1, ge=1),
    success: str | None = None,
    error: str | None = None,
):
    """文件管理页面：分页浏览、下载、删除服务器上的文件。需要 token 验证。"""
    # Token 验证
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            return HTMLResponse(
                content=f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>文件管理</title>
<style>body{{font-family:sans-serif;max-width:600px;margin:40px auto;padding:0 20px;}}
.msg{{padding:12px;border-radius:4px;margin-bottom:16px;}}
.msg.error{{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb;}}</style></head>
<body><h2>📁 文件管理</h2>
<div class="msg error">❌ 需要有效的访问口令</div>
<form method="get" action="/api/v1/novels/files">
<input type="text" name="token" placeholder="请输入访问口令" style="width:100%;padding:8px;box-sizing:border-box;">
<button type="submit" style="margin-top:12px;padding:10px 24px;background:#007acc;color:#fff;border:none;border-radius:4px;cursor:pointer;">验证</button>
</form></body></html>""",
                status_code=403,
            )

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

    # 构建文件列表 HTML
    rows_html = ""
    if not files:
        rows_html = '<tr><td colspan="4" style="text-align:center;padding:24px;color:#666;">暂无文件</td></tr>'
    else:
        for f in files:
            safe_fn = html_mod.escape(f.filename)
            encoded_fn = quote(f.filename, safe="")
            dl_url = f"/api/v1/novels/{encoded_fn}/download?token={quote(token or '', safe='')}"
            mod_time = f.modified_time.strftime("%Y-%m-%d %H:%M")
            rows_html += f"""<tr>
<td>{safe_fn}</td>
<td>{_format_file_size(f.file_size)}</td>
<td>{mod_time}</td>
<td class="actions">
<a href="{dl_url}" class="btn-download" download>下载</a>
<form method="post" action="/api/v1/novels/{encoded_fn}/delete?token={quote(token or '', safe='')}" class="delete-form" onsubmit="return confirm('确定删除 {safe_fn}？');">
<button type="submit" class="btn-delete">删除</button>
</form>
</td>
</tr>"""

    # 分页控件
    pagination_html = ""
    if total_pages > 1:
        pagination_html = '<div class="pagination">'
        if page > 1:
            pagination_html += f'<a href="?token={quote(token or "", safe="")}&page={page - 1}">上一页</a>'
        pagination_html += f'<span>第 {page} / {total_pages} 页（共 {total} 个文件）</span>'
        if page < total_pages:
            pagination_html += f'<a href="?token={quote(token or "", safe="")}&page={page + 1}">下一页</a>'
        pagination_html += '</div>'
    elif total > 0:
        pagination_html = f'<div class="pagination"><span>共 {total} 个文件</span></div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>文件管理</title>
<style>
  body {{ font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }}
  .msg {{ padding: 12px; border-radius: 4px; margin-bottom: 16px; }}
  .msg.success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
  .msg.error {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; font-weight: bold; }}
  .actions {{ white-space: nowrap; }}
  .btn-download {{ display: inline-block; padding: 4px 12px; background: #007acc; color: #fff; border-radius: 4px; text-decoration: none; font-size: 13px; }}
  .btn-download:hover {{ background: #005999; }}
  .btn-delete {{ padding: 4px 12px; background: #dc3545; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }}
  .btn-delete:hover {{ background: #a71d2a; }}
  .delete-form {{ display: inline; }}
  .pagination {{ margin-top: 16px; text-align: center; font-size: 14px; color: #666; }}
  .pagination a {{ display: inline-block; padding: 6px 16px; margin: 0 4px; background: #e9ecef; color: #333; border-radius: 4px; text-decoration: none; }}
  .pagination a:hover {{ background: #ddd; }}
  .pagination span {{ display: inline-block; padding: 6px 12px; }}
</style>
</head>
<body>
<h2>📁 文件管理</h2>
{msg_html}
<table>
<thead>
<tr><th>文件名</th><th>大小</th><th>修改时间</th><th>操作</th></tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
{pagination_html}
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── 文件删除 ───────────────────────────────────────

@router.post("/{filename}/delete")
async def delete_file(
    filename: str,
    token: str | None = Query(None),
    request: Request = None,
):
    """删除服务器上的文件。

    需要配置 FILE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需传入一致的 token。
    浏览器请求成功后重定向回文件管理页面。
    """
    accept = request.headers.get("accept", "") if request else "" if request else ""
    is_browser = "text/html" in accept

    # 开关检查
    if not settings.file_download_enabled:
        err_msg = "文件下载功能未启用（FILE_DOWNLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    # Token 验证
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            err_msg = "无效的访问口令"
            if is_browser:
                return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
            raise HTTPException(status_code=403, detail=err_msg)

    # 安全路径校验
    try:
        file_path = file_service._safe_path(filename)
    except ValueError as e:
        err_msg = str(e)
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    if not file_path.exists():
        err_msg = "文件不存在"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=404, detail=err_msg)

    if not file_path.is_file():
        err_msg = "无效的文件"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    try:
        file_path.unlink()
    except Exception as e:
        err_msg = f"删除失败: {e}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=500, detail=err_msg)

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&success={quote(f'已删除: {filename}')}",
            status_code=303,
        )

    return {"success": True, "filename": filename}


# ─── 远程下载页面 ───────────────────────────────────

@router.get("/download", response_class=HTMLResponse, summary="远程下载页面（浏览器访问）")
async def download_page(
    success: str | None = None,
    error: str | None = None,
):
    """简易远程下载页面（浏览器访问用）。"""
    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ 下载成功: {html_mod.escape(success)}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {html_mod.escape(error)}</div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>远程下载</title>
<style>
  body {{ font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; }}
  form {{ border: 1px solid #ddd; padding: 24px; border-radius: 8px; background: #fafafa; }}
  label {{ display: block; margin: 12px 0 4px; font-weight: bold; }}
  input[type=text] {{ width: 100%; padding: 8px; box-sizing: border-box; }}
  button {{ margin-top: 16px; padding: 10px 24px; background: #007acc; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }}
  button:hover {{ background: #005999; }}
  .tip {{ color: #666; font-size: 14px; margin-top: 8px; }}
  .msg {{ padding: 12px; border-radius: 4px; margin-bottom: 16px; }}
  .msg.success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
  .msg.error {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
</style>
</head>
<body>
<h2>📥 远程下载</h2>
{msg_html}
<form action="/api/v1/novels/download" method="post">
  <label for="url">下载链接</label>
  <input type="text" name="url" id="url" placeholder="https://example.com/file.txt" required>
  <label for="token">访问口令</label>
  <input type="text" name="token" id="token" placeholder="如需口令请在此输入">
  <button type="submit">下载</button>
  <div class="tip">支持 http:// 和 https:// 协议的 URL</div>
</form>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── 远程下载 ───────────────────────────────────────

@router.post("/download", response_model=DownloadResponse)
async def download_novel(
    url: str | None = Form(None),
    token: str | None = Form(None),
    request: Request = None,
    body: DownloadRequest | None = None,
):
    """从 URL 下载文件到配置目录（自动防同名覆盖）。

    需要配置 REMOTE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需传入一致的 token。
    浏览器下载成功后自动重定向回下载页面并显示结果。
    """
    # 判断是否为浏览器请求
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    # 兼容 JSON 请求体和表单提交
    if url is None and body is not None:
        url = body.url
        token = token or body.token

    # 开关检查
    if not settings.remote_download_enabled:
        err_msg = "远程下载功能未启用（REMOTE_DOWNLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/download?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    # Token 验证（配置为空字符串则跳过）
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
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

    # 浏览器请求 → 重定向回下载页面显示成功
    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/download?success={quote(result['filename'])}",
            status_code=303,
        )

    # API 请求 → 返回 JSON
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
