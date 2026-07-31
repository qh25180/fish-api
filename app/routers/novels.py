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


# ─── 辅助：返回索引链接 ─────────────────────────────

def _back_to_index_html(token: str | None) -> str:
    """如果 token 有效，返回「← 返回索引」链接 HTML，否则返回空字符串。"""
    if not token:
        return ""
    t = quote(token, safe="")
    return f'<div style="margin-bottom:12px"><a href="/api/v1/novels/pages?token={t}" style="color:#007acc;text-decoration:none;font-size:14px;">← 返回索引</a></div>'


# ─── 文件列表 API ───────────────────────────────────

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


# ─── 章节 / 内容 API ───────────────────────────────

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


# ─── 短链接索引页 ───────────────────────────────────

_INDEX_STYLE = """
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; }
  .msg { padding: 12px; border-radius: 4px; margin-bottom: 16px; }
  .msg.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
  .card { display: block; border: 1px solid #ddd; border-radius: 8px; padding: 18px 20px; margin-bottom: 12px; text-decoration: none; color: inherit; background: #fafafa; transition: background 0.15s; }
  .card:hover { background: #e9ecef; }
  .card-title { font-size: 16px; font-weight: bold; margin-bottom: 4px; }
  .card-desc { font-size: 13px; color: #666; }
  h2 { font-size: 20px; }
  @media (max-width: 720px) {
    body { margin: 20px auto; padding: 0 12px; }
    h2 { font-size: 18px; }
    .card { padding: 14px 16px; }
  }
</style>
"""


def _pages_index_html(token: str | None) -> str:
    """渲染短链接索引页 HTML。token 无效时返回 403 页。"""
    # Token 验证
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>导航</title>
{_INDEX_STYLE}</head>
<body><h2>📑 导航</h2>
<div class="msg error">❌ 需要有效的访问口令</div>
<form method="get" action="/p">
<input type="text" name="token" placeholder="请输入访问口令" style="width:100%;padding:8px;box-sizing:border-box;">
<button type="submit" style="margin-top:12px;padding:10px 24px;background:#007acc;color:#fff;border:none;border-radius:4px;cursor:pointer;">验证</button>
</form></body></html>"""

    t = quote(token, safe="")
    pages = [
        ("[文本阅读]", "在线阅读服务器上的文本", f"/api/v1/novels/read?token={t}"),
        ("[书籍搜索]", "搜索并下载书籍", f"/api/v1/search-page?token={t}"),
        ("[文件上传]", "上传本地文件到服务器，支持分片上传", f"/api/v1/novels/upload?token={t}"),
        ("[远程下载]", "从 URL 拉取文件到服务器", f"/api/v1/novels/download?token={t}"),
        ("[文件管理]", "浏览、下载、删除服务器上的文件", f"/api/v1/novels/files?token={t}"),
    ]

    cards_html = ""
    for title, desc, href in pages:
        cards_html += f"""<a class="card" href="{href}">
<div class="card-title">{html_mod.escape(title)}</div>
<div class="card-desc">{html_mod.escape(desc)}</div>
</a>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>导航</title>
{_INDEX_STYLE}
</head>
<body>
<h2>📑 导航</h2>
{cards_html}
</body>
</html>"""


@router.get("/pages", response_class=HTMLResponse, summary="短链接索引页（浏览器访问）")
async def pages_index(
    token: str | None = Query(None),
):
    """所有页面入口的索引页。需要 token 验证。"""
    return HTMLResponse(content=_pages_index_html(token))


# ─── 上传页面 ───────────────────────────────────────

@router.get("/upload", response_class=HTMLResponse, summary="上传页面（浏览器访问）")
async def upload_page(
    success: str | None = None,
    error: str | None = None,
    filename: str | None = None,
    token: str | None = None,
):
    """简易文件上传页面（浏览器访问用），支持分片上传。"""
    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ 上传成功: {html_mod.escape(success)}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {html_mod.escape(error)}</div>'

    chunk_size = settings.upload_chunk_size_kb * 1024
    back_html = _back_to_index_html(token)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>文件上传</title>
<style>
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
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
  @media (max-width: 720px) {{
    body {{ margin: 16px auto; padding: 0 12px; }}
    form {{ padding: 16px; }}
    h2 {{ font-size: 18px; }}
    button {{ width: 100%; padding: 12px; font-size: 15px; }}
  }}
</style>
</head>
<body>
{back_html}
<h2>[文件上传]</h2>
{msg_html}
<form id="uploadForm">
  <label for="file">选择文件</label>
  <input type="file" name="file" id="file" required>
  <div class="file-info" id="fileInfo"></div>
  <label for="token">访问口令</label>
  <input type="text" name="token" id="token" placeholder="如需口令请在此输入">
<script>
(function() {{
  const params = new URLSearchParams(location.search);
  const t = params.get('token');
  if (t) document.getElementById('token').value = t;
}})();
</script>
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

      status.innerHTML = '正在合并文件...';
      const completeData = new FormData();
      completeData.append('upload_id', uploadId);
      if (token) completeData.append('token', token);

      const completeResp = await fetch('/api/v1/novels/upload/complete', {{ method: 'POST', body: completeData }});
      if (!completeResp.ok) {{
        const err = await completeResp.json();
        throw new Error(err.detail || '合并失败');
      }}

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
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    if not settings.upload_enabled:
        err_msg = "上传功能未启用（UPLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/upload?error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

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
    from pathlib import Path
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            return HTMLResponse(
                content=f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>文件管理</title>
<style>body{{font-family:sans-serif;max-width:600px;margin:40px auto;padding:0 20px;}}
.msg{{padding:12px;border-radius:4px;margin-bottom:16px;}}
.msg.error{{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb;}}</style></head>
<body><h2>[文件管理]</h2>
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

    hidden_books = _load_hidden_books()
    rows_html = ""
    if not files:
        rows_html = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#666;">暂无文件</td></tr>'
    else:
        for f in files:
            safe_fn = html_mod.escape(f.filename)
            encoded_fn = quote(f.filename, safe="")
            dl_url = f"/api/v1/novels/{encoded_fn}/download?token={quote(token or '', safe='')}"
            mod_time = f.modified_time.strftime("%Y-%m-%d %H:%M")
            book_name = Path(f.filename).stem
            is_hidden = book_name in hidden_books
            row_class = ' class="hidden-row"' if is_hidden else ''
            hide_btn_text = "显示" if is_hidden else "隐藏"
            hide_btn_class = "btn-unhide" if is_hidden else "btn-hide"
            author_escaped = html_mod.escape(f.author)
            rows_html += f"""<tr{row_class}>
<td>{safe_fn}</td>
<td>{_format_file_size(f.file_size)}</td>
<td>{author_escaped}<br><a href="#" onclick="event.preventDefault();var a=document.getElementById('author-{encoded_fn}');a.style.display=a.style.display==='none'?'block':'none';return false;" style="font-size:12px;color:#007acc;">修改</a></td>
<td>{mod_time}</td>
<td class="actions">
<a href="{dl_url}" class="btn-download" download>下载</a>
<form method="post" action="/api/v1/novels/{encoded_fn}/delete?token={quote(token or '', safe='')}" class="delete-form" onsubmit="return confirm('确定删除 {safe_fn}？');">
<button type="submit" class="btn-delete">删除</button>
</form>
<form method="post" action="/api/v1/novels/{encoded_fn}/hide?token={quote(token or '', safe='')}" class="delete-form">
<button type="submit" class="{hide_btn_class}">{hide_btn_text}</button>
</form>
<button type="button" class="btn-rename" onclick="var f=document.getElementById('rename-{encoded_fn}');f.style.display=f.style.display==='block'?'none':'block'">重命名</button>
<form method="post" action="/api/v1/novels/{encoded_fn}/rename?token={quote(token or '', safe='')}" class="rename-form" id="rename-{encoded_fn}">
<input type="text" name="new_name" value="{safe_fn}" required>
<button type="submit" style="background:#007acc;color:#fff;border:none;border-radius:4px;">确认</button>
</form>
<form method="post" action="/api/v1/novels/{encoded_fn}/author?token={quote(token or '', safe='')}" class="rename-form" id="author-{encoded_fn}" style="display:none;">
<input type="text" name="new_author" value="{author_escaped}" required style="width:120px;">
<button type="submit" style="background:#007acc;color:#fff;border:none;border-radius:4px;">确认</button>
</form>
</td>
</tr>"""

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

    back_html = _back_to_index_html(token)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>文件管理</title>
<style>
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
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
  .btn-hide {{ padding: 4px 12px; background: #6c757d; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }}
  .btn-hide:hover {{ background: #545b62; }}
  .btn-unhide {{ padding: 4px 12px; background: #28a745; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }}
  .btn-unhide:hover {{ background: #218838; }}
  .hidden-row {{ opacity: 0.5; }}
  .btn-rename {{ padding: 4px 12px; background: #17a2b8; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }}
  .btn-rename:hover {{ background: #138496; }}
  .rename-form {{ display: none; margin-top: 8px; }}
  .rename-form input {{ width: 200px; padding: 4px 8px; font-size: 13px; }}
  .rename-form button {{ padding: 4px 12px; font-size: 13px; }}
  .pagination {{ margin-top: 16px; text-align: center; font-size: 14px; color: #666; }}
  .pagination a {{ display: inline-block; padding: 6px 16px; margin: 0 4px; background: #e9ecef; color: #333; border-radius: 4px; text-decoration: none; }}
  .pagination a:hover {{ background: #ddd; }}
  .pagination span {{ display: inline-block; padding: 6px 12px; }}
  @media (max-width: 720px) {{
    body {{ margin: 16px auto; padding: 0 8px; }}
    h2 {{ font-size: 18px; }}
    /* 表格横向滚动适配小屏 */
    .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
    table {{ min-width: 520px; }}
    th, td {{ padding: 8px 8px; font-size: 13px; }}
  }}
</style>
</head>
<body>
{back_html}
<h2>[文件管理]</h2>
{msg_html}
<div class="table-wrap">
<table>
<thead>
<tr><th>文件名</th><th>大小</th><th>作者</th><th>修改时间</th><th>操作</th></tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>
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

    if not settings.file_download_enabled:
        err_msg = "文件下载功能未启用（FILE_DOWNLOAD_ENABLED=false）"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=403, detail=err_msg)

    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            err_msg = "无效的访问口令"
            if is_browser:
                return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
            raise HTTPException(status_code=403, detail=err_msg)

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
    token: str | None = Query(None),
    request: Request = None,
):
    """隐藏/显示书籍（从阅读器隐藏）。"""
    accept = request.headers.get("accept", "") if request else "" if request else ""
    is_browser = "text/html" in accept

    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            err_msg = "无效的访问口令"
            if is_browser:
                return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
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
            url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&success={quote(msg)}",
            status_code=303,
        )

    return {"success": True, "filename": filename, "hidden": name in hidden}


# ─── 文件重命名 ─────────────────────────────────────

@router.post("/{filename}/rename")
async def rename_book(
    filename: str,
    new_name: str = Form(...),
    token: str | None = Query(None),
    request: Request = None,
):
    """重命名书籍文件，同步更新进度文件。"""
    accept = request.headers.get("accept", "") if request else "" if request else ""
    is_browser = "text/html" in accept

    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            err_msg = "无效的访问口令"
            if is_browser:
                return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
            raise HTTPException(status_code=403, detail=err_msg)

    # 安全校验
    try:
        old_path = file_service._safe_path(filename)
    except ValueError as e:
        err_msg = str(e)
        if is_browser:
            return RedirectResponse(url=f"/usr/local/dev/qhapi/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    if not old_path.exists():
        err_msg = "文件不存在"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=404, detail=err_msg)

    # 构建新文件名
    old_stem = Path(filename).stem
    suffix = old_path.suffix
    safe_new_name = os.path.basename(new_name.strip())
    if not safe_new_name:
        err_msg = "新名称不能为空"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    # 确保新文件名有扩展名
    if not Path(safe_new_name).suffix:
        safe_new_name += suffix

    new_path = old_path.parent / safe_new_name

    if new_path.exists() and new_path != old_path:
        err_msg = f"文件名已存在: {safe_new_name}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=400, detail=err_msg)

    try:
        old_path.rename(new_path)
    except Exception as e:
        err_msg = f"重命名失败: {e}"
        if is_browser:
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
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
            url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&success={quote(f'已重命名: {filename} → {safe_new_name}')}",
            status_code=303,
        )

    return {"success": True, "old_filename": filename, "new_filename": safe_new_name}


# ─── 修改作者 ───────────────────────────────────────

@router.post("/{filename}/author")
async def update_author(
    filename: str,
    new_author: str = Form(...),
    token: str | None = Query(None),
    request: Request = None,
):
    """修改文件的作者信息。"""
    accept = request.headers.get("accept", "") if request else ""
    is_browser = "text/html" in accept

    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            err_msg = "无效的访问口令"
            if is_browser:
                return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
            raise HTTPException(status_code=403, detail=err_msg)

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
            return RedirectResponse(url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&error={quote(err_msg)}", status_code=303)
        raise HTTPException(status_code=500, detail=err_msg)

    if is_browser:
        return RedirectResponse(
            url=f"/api/v1/novels/files?token={quote(token or '', safe='')}&success={quote(f'已更新作者: {filename} → {new_author}')}",
            status_code=303,
        )

    return {"success": True, "filename": filename, "author": new_author.strip()}


# ─── 远程下载页面 ───────────────────────────────────

@router.get("/download", response_class=HTMLResponse, summary="远程下载页面（浏览器访问）")
async def download_page(
    success: str | None = None,
    error: str | None = None,
    token: str | None = None,
):
    """简易远程下载页面（浏览器访问用）。"""
    msg_html = ""
    if success:
        msg_html = f'<div class="msg success">✅ 下载成功: {html_mod.escape(success)}</div>'
    elif error:
        msg_html = f'<div class="msg error">❌ {html_mod.escape(error)}</div>'

    back_html = _back_to_index_html(token)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>远程下载</title>
<style>
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
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
  @media (max-width: 720px) {{
    body {{ margin: 16px auto; padding: 0 12px; }}
    form {{ padding: 16px; }}
    h2 {{ font-size: 18px; }}
    button {{ width: 100%; padding: 12px; font-size: 15px; }}
  }}
</style>
</head>
<body>
{back_html}
<h2>[远程下载]</h2>
{msg_html}
<form action="/api/v1/novels/download" method="post">
  <label for="url">下载链接</label>
  <input type="text" name="url" id="url" placeholder="https://example.com/file.txt" required>
  <label for="token">访问口令</label>
  <input type="text" name="token" id="token" placeholder="如需口令请在此输入">
  <button type="submit">下载</button>
<script>
(function() {{
  const params = new URLSearchParams(location.search);
  const t = params.get('token');
  if (t) document.getElementById('token').value = t;
}})();
</script>
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
    token: str | None = Query(None, description="访问口令"),
):
    """下载服务器上的文件到本地（浏览器/curl 直接访问）。

    需要配置 FILE_DOWNLOAD_ENABLED=true 开启此接口。
    如果配置了 API_TOKEN，需在查询参数中传入一致的 token。
    """
    if not settings.file_download_enabled:
        raise HTTPException(
            status_code=403,
            detail="文件下载未启用（FILE_DOWNLOAD_ENABLED=false）",
        )

    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            raise HTTPException(
                status_code=403,
                detail="无效的访问口令",
            )

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

_READER_STYLE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; overflow: hidden; }
  body { font-family: var(--font-family, "Noto Serif SC", serif); background: var(--bg-color, #f5f1eb); color: var(--text-color, #333); }
  .container { max-width: 900px; margin: 0 auto; padding: 10px 20px; height: 100vh; height: 100dvh; display: flex; flex-direction: column; overflow: hidden; }
  .header { display: flex; align-items: center; padding: 8px 0; border-bottom: 1px solid #ddd; gap: 8px; flex-shrink: 0; }
  .header .book-name { flex: 1; font-size: 16px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .header .page-stat { font-size: 12px; color: #999; white-space: nowrap; margin-right: 8px; }
  .header .icon-btn { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: 1px solid #ccc; border-radius: 6px; background: transparent; cursor: pointer; font-size: 16px; color: #555; transition: background 0.15s; text-decoration: none; flex-shrink: 0; }
  .header .icon-btn:hover { background: #e9ecef; }

  /* 选书列表 */
  .book-list { list-style: none; margin-top: 16px; }
  .book-item { padding: 14px 16px; border: 1px solid #ddd; border-radius: 6px; margin-bottom: 8px; cursor: pointer; background: var(--card-bg, #fff); transition: background 0.15s; }
  .book-item:hover { background: #e9ecef; }
  .book-name-lg { font-size: 16px; font-weight: bold; }
  .book-info { font-size: 13px; color: #888; margin-top: 4px; }

  /* 章节列表弹窗 */
  .modal.chapters-modal { width: 460px; max-width: 94vw; }
  .chapters-jump { display: flex; gap: 6px; margin: 8px 0; }
  .chapters-jump input { flex: 1; padding: 8px 10px; font-size: 13px; border: 1px solid color-mix(in srgb, var(--text-color, #333) 20%, transparent); border-radius: 6px; background: transparent; color: var(--text-color, #333); }
  .chapters-jump input:focus { outline: none; border-color: #007acc; }
  .chapters-jump .jump-btn { padding: 8px 14px; background: #007acc; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; flex-shrink: 0; }
  .chapters-jump .jump-btn:hover { background: #005999; }
  /* 虚拟滚动：固定行高 + 内容绝对定位 */
  .chapters-modal .chapters-list { position: relative; max-height: 55vh; min-height: 200px; overflow-y: auto; border: 1px solid color-mix(in srgb, var(--text-color, #333) 15%, transparent); border-radius: 6px; margin: 8px 0; }
  .chapters-modal .chapter-item { position: absolute; left: 0; right: 0; height: 38px; line-height: 38px; padding: 0 14px 0 8px; border-bottom: 1px solid color-mix(in srgb, var(--text-color, #333) 8%, transparent); cursor: pointer; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; box-sizing: border-box; }
  .chapters-modal .chapter-item:last-child { border-bottom: none; }
  .chapters-modal .chapter-item:hover { background: color-mix(in srgb, var(--text-color, #333) 6%, transparent); }
  .chapters-modal .chapter-item.active { background: #007acc; color: #fff; }
  .chapters-modal .chapter-item .ch-num { color: color-mix(in srgb, var(--text-color, #333) 45%, transparent); font-size: 12px; margin-right: 10px; display: inline-block; }
  .chapters-modal .chapter-item.active .ch-num { color: rgba(255, 255, 255, 0.75); }

  /* 阅读区域 — 自适应无滚动，文本区域与页面同色（沉浸阅读） */
  .reader-wrap { flex: 1; position: relative; display: flex; align-items: stretch; min-height: 0; }
  .reader { background: var(--bg-color, #f5f1eb); border-radius: 6px; padding: 20px 30px; flex: 1; display: flex; flex-direction: column; overflow: hidden; margin: 8px 0; }
  .reader-title { font-size: calc(var(--font-size, 17px) + 2px); font-weight: bold; text-align: center; margin-bottom: 10px; color: color-mix(in srgb, var(--text-color, #333) 60%, transparent); flex-shrink: 0; }
  .reader-text { flex: 1; overflow: hidden; font-size: var(--font-size, 17px); line-height: var(--line-height, 1.9); white-space: pre-wrap; word-wrap: break-word; }

  /* 章节加载中提示 */
  .reader-loading { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: color-mix(in srgb, var(--text-color, #333) 55%, transparent); font-size: 14px; z-index: 20; pointer-events: none; }
  .spinner { width: 28px; height: 28px; border: 3px solid color-mix(in srgb, var(--text-color, #333) 20%, transparent); border-top-color: var(--text-color, #333); border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to {{ transform: rotate(360deg); }} }

  /* 导航按钮悬浮两侧 — 竖排窄条，卡片全宽不留白 */
  .nav-left, .nav-right { position: absolute; top: 50%; transform: translateY(-50%); display: flex; flex-direction: column; gap: 8px; z-index: 10; }
  .nav-left { left: 4px; }
  .nav-right { right: 4px; }
  .nav-btn { width: 28px; padding: 12px 3px; border: none; border-radius: 10px;
    background: rgba(128, 128, 128, 0.35); color: #fff; cursor: pointer;
    font-size: 12px; letter-spacing: 3px;
    writing-mode: vertical-rl; text-orientation: upright;
    opacity: 0.55; transition: opacity 0.2s; }
  .nav-btn:hover { opacity: 1; }
  .nav-btn:disabled { opacity: 0.15; cursor: not-allowed; }
  .nav-btn .nav-icon { display: none; }

  /* 大范围点击热区 — 上方整行+左侧整列=上一页；下方整行+右侧整列=下一页 */
  .tap-zone { position: absolute; cursor: pointer; background: transparent; }
  /* 点击反馈：跟随主题文字色 10% 淡色，深浅主题均自然，几乎不干扰阅读 */
  .tap-zone:active, .tap-zone.tapping { background: rgba(128, 128, 128, 0.10); background: color-mix(in srgb, var(--text-color, #333) 10%, transparent); }
  .tap-zone-prev-top { left: 0; top: 0; width: 100%; height: 20%; min-height: 80px; z-index: 5; }
  .tap-zone-prev-left { left: 0; top: 0; width: 56px; height: 100%; z-index: 6; }
  .tap-zone-next-bottom { left: 0; bottom: 0; width: 100%; height: 20%; min-height: 80px; z-index: 5; }
  .tap-zone-next-right { right: 0; top: 0; width: 56px; height: 100%; z-index: 6; }

  /* 设置弹窗 */
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 1000; align-items: center; justify-content: center; }
  .modal-overlay.show { display: flex; }
  .modal { background: var(--card-bg, #fff); color: var(--text-color, #333); border-radius: 12px; padding: 24px; width: 340px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
  .modal h3 { margin-bottom: 16px; font-size: 16px; }
  .modal label { display: block; margin: 12px 0 4px; font-size: 13px; color: #666; }
  .modal input[type=range] { width: 100%; }
  .modal .range-val { text-align: center; font-size: 16px; margin-top: 4px; }
  .color-presets { display: flex; gap: 8px; margin: 8px 0; }
  .color-presets button { width: 40px; height: 40px; border-radius: 8px; border: 2px solid transparent; cursor: pointer; }
  .color-presets button.active { border-color: #007acc; }
  .modal .btn-confirm { display: block; width: 100%; margin-top: 16px; padding: 10px; background: #007acc; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 15px; }
  .modal .btn-confirm:hover { background: #005999; }

  /* 底部留白 */
  .footer-spacer { flex-shrink: 0; height: 20px; }

  .loading { text-align: center; padding: 40px; color: #888; }
  .status { text-align: center; color: #888; padding: 40px; font-size: 14px; }

  @media (max-width: 720px) {
    .container { padding: 8px 10px; }
    .nav-left { left: 2px; }
    .nav-right { right: 2px; }
    /* 移动端：同样竖排文字，更窄更小 */
    .nav-btn { width: 20px; padding: 10px 2px; font-size: 10px; letter-spacing: 2px;
      border-radius: 8px; background: rgba(128, 128, 128, 0.35); }
    .tap-zone-prev-left, .tap-zone-next-right { width: 48px; }
    .reader { padding: 12px 24px; margin: 8px 0; }
  }
</style>
"""


@router.get("/read", response_class=HTMLResponse, summary="文本阅读器（浏览器访问）")
async def read_page(
    token: str | None = Query(None),
):
    """在线阅读服务器上的文本。

    若配置了 READER_TOKEN_ENABLED=true 且设置了 API_TOKEN，
    则访问本页面需携带有效 token，否则返回 403 错误页。
    """
    # 阅读器 token 验证（可选启用）
    if settings.reader_token_enabled and settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            return HTMLResponse(
                content="""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>文本阅读</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: sans-serif; background: #f5f1eb; color: #333; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }
  .box { text-align: center; }
  h2 { font-size: 18px; margin-bottom: 12px; }
  p { color: #666; font-size: 14px; margin-bottom: 20px; }
  input, button { padding: 10px 14px; font-size: 14px; border-radius: 6px; border: 1px solid #ccc; }
  input { width: 220px; }
  button { background: #007acc; color: #fff; border: none; cursor: pointer; margin-left: 8px; }
  button:hover { background: #005999; }
</style>
</head>
<body>
<div class="box">
  <h2>🔒 需要访问口令</h2>
  <p>文本阅读页面已启用口令验证，请输入有效 token</p>
  <form method="get" action="/api/v1/novels/read">
    <input type="text" name="token" placeholder="请输入访问口令">
    <button type="submit">进入</button>
  </form>
</div>
</body>
</html>""",
                status_code=403,
            )

    back_html = _back_to_index_html(token)
    t = quote(token or "", safe="")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>文本阅读</title>
{_READER_STYLE}
</head>
<body>
<div class="container">
  <!-- 顶部栏 -->
  <div class="header">
    <span class="book-name" id="headerTitle">[文本阅读]</span>
    <span class="page-stat" id="pageInfo"></span>
    <button class="icon-btn" id="btnSettings" onclick="showSettings()" title="阅读设置">⚙️</button>
    <button class="icon-btn" id="btnChapters" onclick="toggleChapterList()" title="章节目录" style="display:none">📑</button>
    <button class="icon-btn" id="btnBack" onclick="backToBooks()" title="返回书架">✕</button>
  </div>

  <!-- 选书 -->
  <div id="bookView" style="flex:1;overflow-y:auto;">
    <div class="loading" id="bookLoading">加载书架...</div>
    <ul class="book-list" id="bookList" style="display:none"></ul>
  </div>

  <!-- 阅读区 -->
  <div id="readerView" style="display:none;flex:1;flex-direction:column;min-height:0;">
    <div class="reader-wrap" style="flex:1;position:relative;">
      <div class="nav-left">
        <button class="nav-btn" id="btnPrevPage" onclick="prevPage()" disabled><span class="nav-icon">◀</span><span class="nav-txt">上一页</span></button>
      </div>
      <!-- 点击热区：上方整行+左侧整列=上一页；下方整行+右侧整列=下一页 -->
      <div class="tap-zone tap-zone-prev-top" onclick="prevPage()" title="上一页"></div>
      <div class="tap-zone tap-zone-prev-left" onclick="prevPage()" title="上一页"></div>
      <div class="tap-zone tap-zone-next-bottom" onclick="nextPage()" title="下一页"></div>
      <div class="tap-zone tap-zone-next-right" onclick="nextPage()" title="下一页"></div>
      <div class="reader">
        <div class="reader-title" id="readerTitle"></div>
        <div class="reader-text" id="readerText"></div>
        <!-- 章节加载中提示 -->
        <div class="reader-loading" id="readerLoading" style="display:none">
          <div class="spinner"></div>
          <span>章节加载中...</span>
        </div>
      </div>
      <div class="nav-right">
        <button class="nav-btn" id="btnNextPage" onclick="nextPage()" disabled><span class="nav-txt">下一页</span><span class="nav-icon">▶</span></button>
      </div>
    </div>
  </div>
  <div class="footer-spacer"></div>
</div>

<!-- 设置弹窗 -->
<div class="modal-overlay" id="settingsModal">
  <div class="modal">
    <h3>阅读设置</h3>
    <label for="fontSizeSlider">字号</label>
    <input type="range" id="fontSizeSlider" min="12" max="32" value="17">
    <div class="range-val" id="fontSizeVal">17px</div>
    <label>背景</label>
    <div class="color-presets" id="colorPresets"></div>
    <button class="btn-confirm" onclick="applySettings()">确定</button>
  </div>
</div>

  <!-- 章节列表弹窗 -->
  <div class="modal-overlay" id="chaptersModal">
    <div class="modal chapters-modal">
      <h3>章节目录</h3>
      <div class="chapters-jump">
        <input type="number" id="chapterJumpInput" min="1" placeholder="输入章节号跳转" onkeydown="if(event.key==='Enter') jumpToChapter()">
        <button class="jump-btn" onclick="jumpToChapter()">跳转</button>
      </div>
      <div class="chapters-list" id="chapterList"></div>
      <button class="btn-confirm" onclick="hideChapters()">关闭</button>
    </div>
  </div>

<script>
(function() {{
  const BASE = '/api/v1/novels';
  const TOKEN = '{t}';

  // ─── 设置 ──────────────────────────
  const THEMES = [
    {{ name: '护眼黄', bg: '#f5f1eb', card: '#fff', text: '#333' }},
    {{ name: '纯白',   bg: '#ffffff', card: '#fff', text: '#333' }},
    {{ name: '暗黑',   bg: '#1a1a2e', card: '#16213e', text: '#e0e0e0' }},
    {{ name: '羊皮纸', bg: '#f4ecd8', card: '#faf3e6', text: '#4a3b32' }},
    {{ name: '墨绿',   bg: '#d4e6d8', card: '#e8f0e8', text: '#2d3a3a' }},
  ];
  let settings = JSON.parse(localStorage.getItem('qhapi_reader_settings') || '{{}}');
  if (!settings.fontSize) settings = {{ fontSize: 17, themeIndex: 0 }};
  let savedSettings = null;
  let sliderTimer = null;
  applyTheme(settings);

  function applyTheme(s, save = true) {{
    const t = THEMES[s.themeIndex] || THEMES[0];
    document.documentElement.style.setProperty('--font-size', s.fontSize + 'px');
    document.documentElement.style.setProperty('--line-height', (s.fontSize > 22 ? 1.7 : 1.9));
    document.documentElement.style.setProperty('--bg-color', t.bg);
    document.documentElement.style.setProperty('--card-bg', t.card);
    document.documentElement.style.setProperty('--text-color', t.text);
    if (save) localStorage.setItem('qhapi_reader_settings', JSON.stringify(s));
  }}

  // 等浏览器应用新样式后再重新分页
  function reflowAfterTheme() {{
    if (!chapterText) return;
    requestAnimationFrame(() => reflowPage());
  }}

  window.showSettings = function() {{
    savedSettings = JSON.parse(JSON.stringify(settings));
    const modal = document.getElementById('settingsModal');
    modal.classList.add('show');
    const slider = document.getElementById('fontSizeSlider');
    slider.value = settings.fontSize;
    document.getElementById('fontSizeVal').textContent = settings.fontSize + 'px';
    const presets = document.getElementById('colorPresets');
    presets.innerHTML = '';
    THEMES.forEach((t, i) => {{
      const btn = document.createElement('button');
      btn.style.background = t.bg;
      btn.style.borderColor = t.bg;
      if (i === settings.themeIndex) btn.classList.add('active');
      btn.title = t.name;
      btn.onclick = () => {{
        presets.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        settings.themeIndex = i;
        applyTheme(settings, false); // 实时预览背景色
      }};
      presets.appendChild(btn);
    }});
    slider.oninput = function() {{
      document.getElementById('fontSizeVal').textContent = this.value + 'px';
      settings.fontSize = parseInt(this.value);
      applyTheme(settings, false); // 实时预览字号
      // 防抖：停止拖动后自动重新分页
      clearTimeout(sliderTimer);
      sliderTimer = setTimeout(reflowAfterTheme, 120);
    }};
  }};

  window.applySettings = function() {{
    document.getElementById('settingsModal').classList.remove('show');
    applyTheme(settings); // 保存设置
    reflowAfterTheme();
  }};

  // 点击遮罩 = 取消，恢复原设置
  document.getElementById('settingsModal').onclick = function(e) {{
    if (e.target === this) {{
      settings = savedSettings || settings;
      applyTheme(settings);
      this.classList.remove('show');
      reflowAfterTheme();
    }}
  }};

  // ─── 触摸点击反馈（移动端） ─────────
  // :active 在移动浏览器上不可靠，且会被系统 tap 高亮覆盖，
  // 这里用 touch 事件手动加 .tapping 类控制反馈色
  document.querySelectorAll('.tap-zone').forEach(z => {{
    z.addEventListener('touchstart', () => z.classList.add('tapping'), {{ passive: true }});
    z.addEventListener('touchend', () => z.classList.remove('tapping'));
    z.addEventListener('touchcancel', () => z.classList.remove('tapping'));
    // 鼠标端也统一（保留 :active 同时加类，更可靠）
    z.addEventListener('mousedown', () => z.classList.add('tapping'));
    z.addEventListener('mouseup', () => z.classList.remove('tapping'));
    z.addEventListener('mouseleave', () => z.classList.remove('tapping'));
  }});

  // ─── 分页计算（实测，保证不溢出） ──────
  function findMaxFit(text, el) {{
    // 二分查找：在当前视口内能完整显示的最长前缀
    let lo = 1, hi = text.length, best = 0;
    while (lo <= hi) {{
      const mid = (lo + hi) >> 1;
      el.textContent = text.substring(0, mid);
      if (el.scrollHeight <= el.clientHeight + 1) {{
        best = mid; lo = mid + 1;
      }} else {{
        hi = mid - 1;
      }}
    }}
    return Math.max(1, best);
  }}

  // 构建页面历史：从章节开头逐页测量，直到覆盖恢复位置
  function buildPageHistory() {{
    const el = document.getElementById('readerText');
    if (!el || !el.clientHeight) {{ pageHistory = [pageOffset]; return; }}
    const target = Math.min(pageOffset, Math.max(0, chapterText.length - 1));
    const hist = [0];
    if (target > 0) {{
      let pos = 0;
      while (pos < target) {{
        const n = findMaxFit(chapterText.substring(pos), el);
        if (n <= 0) break;
        pos += n;
        if (pos >= target) break; // 恢复位置落在本页内，不再记录下一页起点
        hist.push(pos);
      }}
    }}
    pageHistory = hist;
    // 恢复位置所在页的起点（该页完整包含上次读到的地方）
    pageOffset = hist[hist.length - 1];
  }}

  // ─── 数据 ──────────────────────────
  let books = [];
  let chapters = [];
  let book = null;
  let chapterIndex = 0;
  let chapterText = '';
  let pageOffset = 0;
  let snippetLen = 500;
  let pageHistory = []; // 已访问页面的起始位置栈（栈顶 = 当前页起点）
  let jumpToEnd = false; // 切上一章后定位到章节末尾

  async function api(path, params) {{
    const url = new URL(path, location.origin);
    if (TOKEN) url.searchParams.set('token', TOKEN);
    if (params) Object.entries(params).forEach(([k,v]) => url.searchParams.set(k, v));
    const resp = await fetch(url);
    const raw = await resp.json();
    const data = raw.detail || raw;
    if (data.isSuccess === false) throw new Error(data.errorMsg || '请求失败');
    return data.data !== undefined ? data.data : data;
  }}

  // ─── 选书 ──────────────────────────
  async function loadBooks() {{
    try {{
      books = await api('/getBookshelf');
      books.sort((a, b) => (b.durChapterTime || 0) - (a.durChapterTime || 0));
      const list = document.getElementById('bookList');
      list.innerHTML = '';
      books.forEach((b, i) => {{
        const li = document.createElement('li');
        li.className = 'book-item';
        const progress = b.durChapterTitle ? '上次阅读: ' + b.durChapterTitle : '未阅读';
        const author = b.author && b.author !== '未知作者' ? ' · ' + b.author : '';
        li.innerHTML = '<div class="book-name-lg">' + escHtml(b.name) + '</div>'
          + '<div class="book-info">' + escHtml(progress) + author + ' · ' + b.totalChapterNum + ' 章</div>';
        li.onclick = () => selectBook(i);
        list.appendChild(li);
      }});
      document.getElementById('bookLoading').style.display = 'none';
      list.style.display = 'block';
    }} catch (e) {{
      document.getElementById('bookLoading').textContent = '加载失败: ' + e.message;
    }}
  }}

  async function selectBook(index) {{
    book = books[index];
    document.getElementById('headerTitle').textContent = book.name;
    document.getElementById('bookView').style.display = 'none';
    const rv = document.getElementById('readerView');
    rv.style.display = 'flex';
    document.getElementById('btnChapters').style.display = 'inline-flex';

    try {{
      chapters = await api('/getChapterList', {{ url: book.bookUrl }});
      renderChapterList();
      chapterIndex = book.durChapterIndex || 0;
      pageOffset = book.durChapterPos || 0;
      await loadChapter();
    }} catch (e) {{
      document.getElementById('readerText').textContent = '加载章节失败: ' + e.message;
    }}
  }}

  // 返回书架列表（在阅读视图）；在书架页则返回索引页
  window.backToBooks = function() {{
    const rv = document.getElementById('readerView');
    // 已在书架列表页 → 跳转索引页
    if (rv.style.display === 'none') {{
      window.location.href = '/p/' + encodeURIComponent(TOKEN);
      return;
    }}
    rv.style.display = 'none';
    document.getElementById('bookView').style.display = 'block';
    document.getElementById('headerTitle').textContent = '[文本阅读]';
    document.getElementById('pageInfo').textContent = '';
    document.getElementById('btnChapters').style.display = 'none';
    hideChapters();
    loadBooks(); // 刷新列表（保持最近阅读排序）
  }};

  // ─── 章节列表弹窗（虚拟滚动） ─────
  const CH_ITEM_H = 38; // 每章固定行高（与 CSS 一致）
  const CH_BUFFER = 8;  // 上下缓冲行数
  let chScrollTop = 0;

  window.toggleChapterList = function() {{
    const modal = document.getElementById('chaptersModal');
    modal.classList.toggle('show');
    // 打开时滚动到当前章节
    if (modal.classList.contains('show')) {{
      scrollChaptersToCurrent();
    }}
  }};

  window.hideChapters = function() {{
    document.getElementById('chaptersModal').classList.remove('show');
  }};

  // 点击遮罩关闭章节弹窗
  document.getElementById('chaptersModal').onclick = function(e) {{
    if (e.target === this) hideChapters();
  }};

  // 滚动到当前章节
  function scrollChaptersToCurrent() {{
    const list = document.getElementById('chapterList');
    list.scrollTop = chapterIndex * CH_ITEM_H;
  }}

  // 虚拟滚动渲染：只渲染可视区 ± 缓冲
  function renderChapterList() {{
    const list = document.getElementById('chapterList');
    if (!chapters.length) {{
      list.innerHTML = '<div class="chapter-item" style="position:static">暂无章节</div>';
      return;
    }}
    // 容器总高度（占位撑出滚动条）
    const totalH = chapters.length * CH_ITEM_H;
    // 重建：外层占位 + 内部可见区
    list.innerHTML = '';
    const spacer = document.createElement('div');
    spacer.style.height = totalH + 'px';
    spacer.style.position = 'relative';
    list.appendChild(spacer);

    const render = () => {{
      const scrollTop = list.scrollTop;
      const vh = list.clientHeight;
      const startIdx = Math.max(0, Math.floor(scrollTop / CH_ITEM_H) - CH_BUFFER);
      const endIdx = Math.min(chapters.length, Math.ceil((scrollTop + vh) / CH_ITEM_H) + CH_BUFFER);
      // 清理旧节点（保留 spacer）
      spacer.querySelectorAll('.chapter-item').forEach(n => n.remove());
      for (let i = startIdx; i < endIdx; i++) {{
        const ch = chapters[i];
        const div = document.createElement('div');
        div.className = 'chapter-item' + (i === chapterIndex ? ' active' : '');
        div.style.top = (i * CH_ITEM_H) + 'px';
        div.innerHTML = '<span class="ch-num">' + (i + 1) + '</span><span class="ch-title">' + escHtml(ch.title) + '</span>';
        div.onclick = () => {{
          chapterIndex = i; pageOffset = 0; hideChapters(); loadChapter();
        }};
        spacer.appendChild(div);
      }}
    }};

    list.onscroll = render; // 滚动时增量渲染
    render();
  }}

  // 按章节号跳转
  window.jumpToChapter = function() {{
    const input = document.getElementById('chapterJumpInput');
    const n = parseInt(input.value, 10);
    if (!n || n < 1 || n > chapters.length) {{
      input.value = '';
      input.placeholder = '请输入 1-' + chapters.length + ' 的章节号';
      return;
    }}
    chapterIndex = n - 1; pageOffset = 0; hideChapters(); loadChapter();
  }};

  async function loadChapter() {{
    if (chapterIndex < 0 || chapterIndex >= chapters.length) return;
    document.getElementById('readerTitle').textContent = chapters[chapterIndex].title;
    document.getElementById('readerLoading').style.display = 'flex';
    document.getElementById('readerText').style.display = 'none';

    try {{
      chapterText = await api('/getBookContent', {{ url: book.bookUrl, index: chapterIndex }});
      chapterText = htmlToText(chapterText);
      // 上一章切换：定位到本章最后一页
      if (jumpToEnd) {{
        jumpToEnd = false;
        pageOffset = Math.max(0, chapterText.length - 1);
      }}
      // 等待 DOM 布局完成后再分页
      requestAnimationFrame(() => {{
        requestAnimationFrame(() => {{
          document.getElementById('readerLoading').style.display = 'none';
          document.getElementById('readerText').style.display = 'block';
          buildPageHistory(); // 恢复进度：构建从章节开头到当前位置的完整页面历史
          reflowPage(); renderChapterList(); saveProgress();
        }});
      }});
    }} catch (e) {{
      document.getElementById('readerLoading').style.display = 'none';
      document.getElementById('readerText').style.display = 'block';
      document.getElementById('readerText').textContent = '加载失败: ' + e.message;
    }}
  }}

  function reflowPage() {{
    if (pageOffset >= chapterText.length) pageOffset = Math.max(0, chapterText.length - 1);
    const el = document.getElementById('readerText');
    if (!el || !el.clientHeight) {{ snippetLen = 500; return; }}
    const remaining = chapterText.substring(pageOffset);
    snippetLen = findMaxFit(remaining, el);
    const end = Math.min(pageOffset + snippetLen, chapterText.length);
    el.textContent = remaining.substring(0, snippetLen) || '（本章暂无内容）';
    document.getElementById('pageInfo').textContent = (pageOffset + 1) + '-' + end + ' / ' + chapterText.length + '字';
    document.getElementById('btnPrevPage').disabled = (pageOffset <= 0 && chapterIndex <= 0);
    document.getElementById('btnNextPage').disabled = (end >= chapterText.length && chapterIndex >= chapters.length - 1);
  }}

  window.prevPage = function() {{
    // 章首继续点 → 切上一章（翻到上一章末尾）
    if (pageOffset <= 0 && pageHistory.length <= 1) {{
      prevChapter(); return;
    }}
    // 弹出当前页起点，回到上一页起点（栈顶）
    if (pageHistory.length > 1) pageHistory.pop();
    pageOffset = pageHistory[pageHistory.length - 1];
    reflowPage();
    saveProgress();
  }};

  window.nextPage = function() {{
    if (pageOffset + snippetLen >= chapterText.length) {{ nextChapter(); return; }}
    pageOffset += snippetLen;
    pageHistory.push(pageOffset); // 记录新页起点
    reflowPage();
    saveProgress();
  }};

  window.prevChapter = function() {{
    if (chapterIndex <= 0) return;
    jumpToEnd = true; // 切到上一章最后一页
    chapterIndex--; pageOffset = 0; loadChapter();
  }};

  window.nextChapter = function() {{
    if (chapterIndex >= chapters.length - 1) return;
    chapterIndex++; pageOffset = 0; loadChapter();
  }};

  async function saveProgress() {{
    if (!book) return;
    try {{
      await fetch('/saveBookProgress' + (TOKEN ? '?token=' + encodeURIComponent(TOKEN) : ''), {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          name: book.name, author: book.author,
          durChapterIndex: chapterIndex, durChapterPos: pageOffset,
          durChapterTime: Date.now(),
          durChapterTitle: (chapters[chapterIndex] || {{}}).title || ''
        }})
      }});
    }} catch (e) {{}}
  }}

  function escHtml(s) {{
    const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
  }}

  function htmlToText(html) {{
    const d = document.createElement('div'); d.innerHTML = html;
    return d.textContent || d.innerText || '';
  }}

  // ─── 窗口调整 ──────────────────────
  let resizeTimer;
  window.onresize = function() {{
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {{ if (chapterText) reflowPage(); }}, 150);
  }};

  loadBooks();
}})();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)
