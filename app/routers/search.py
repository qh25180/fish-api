"""搜索 API 路由 — 搜索书籍 + 浏览器搜索页面。"""

import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.security import token_for_url, request_token_ok
from app.sources import get_source, list_sources

router = APIRouter(prefix="/api/v1", tags=["search"])

# Jinja2 模板
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _redirect_login() -> RedirectResponse:
    """未认证的页面请求：跳转到 /login。"""
    return RedirectResponse(url="/login", status_code=302)


def _require_token(request: Request = None):
    """若配置了 API_TOKEN，校验 token（Bearer/Cookie），无效抛 403。"""
    if settings.api_token and (request is None or not request_token_ok(request)):
        raise HTTPException(status_code=403, detail="无效的访问口令")


def _token_ok(request: Request = None) -> bool:
    """布尔版 token 校验。"""
    if not settings.api_token:
        return True
    return request is not None and request_token_ok(request)


@router.get("/sources")
async def sources_list(
    request: Request = None,
):
    """列出可用搜索源。"""
    _require_token(request)
    return list_sources()


@router.get("/search")
async def search_books(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    source: str = Query("a", description="搜索源名称（a/b/auto）"),
    request: Request = None,
):
    """搜索书籍。"""
    _require_token(request)
    if source == "auto":
        results = []
        for name in ["a", "b"]:
            s = get_source(name)
            if s:
                for r in s.search(q):
                    r["source_title"] = s.title
                    results.append(r)
        return {"source": "auto", "total": len(results), "results": results}

    s = get_source(source)
    if not s:
        raise HTTPException(status_code=400, detail=f"未知搜索源: {source}")
    results = s.search(q)
    for r in results:
        r["source_title"] = s.title
    return {"source": source, "total": len(results), "results": results}


@router.get("/book-detail")
async def book_detail(
    book_id: str = Query(..., description="书籍 ID"),
    source: str = Query("a", description="搜索源名称"),
    request: Request = None,
):
    """获取书籍详情和下载链接。"""
    _require_token(request)
    s = get_source(source)
    if not s:
        raise HTTPException(status_code=400, detail=f"未知搜索源: {source}")
    detail = s.get_detail(book_id)
    return detail


# ─── 搜索页面 ───────────────────────────────────────

@router.get("/search-page", response_class=HTMLResponse, include_in_schema=False)
async def search_page(
    request: Request = None,
):
    """浏览器搜索页面。需要 token 验证（Bearer 或 Cookie）。"""
    if not _token_ok(request):
        return _redirect_login()

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "token": quote(token_for_url(request) or "", safe=""),
            "sources": list_sources(),
        },
    )


# ─── 下载书籍（通过搜索源） ────────────────────────

@router.get("/books/download")
async def download_book(
    book_id: str = Query(..., description="书籍 ID"),
    source: str = Query("a", description="搜索源名称"),
    request: Request = None,
):
    """通过搜索源下载书籍到 novels 目录。"""
    # Token 验证
    if not _token_ok(request):
        return {"success": False, "error": "无效的访问口令"}

    s = get_source(source)
    if not s:
        return {"success": False, "error": f"未知搜索源: {source}"}

    dl_dir = settings.text_files_dir
    dl_dir.mkdir(parents=True, exist_ok=True)

    # 获取书籍详情以提取作者
    detail = s.get_detail(book_id) if source == "a" else {"author": "未知作者"}
    detected_author = detail.get("author", "未知作者")

    try:
        if source == "b":
            # 源B需要下载+解压
            result_path = s.download_and_extract(book_id, str(dl_dir))
            if result_path:
                # 从文件名提取作者
                from app.utils.meta_util import extract_meta
                meta = extract_meta(os.path.basename(result_path))
                detected_author = meta["author"]
                # 保存作者到进度文件
                _save_author_to_progress(os.path.basename(result_path), detected_author)
                return {"success": True, "filename": os.path.basename(result_path)}
            return {"success": False, "error": "下载或解压失败"}

        else:
            # 源A直接下载
            download_url = s.get_download_url(book_id)
            if not download_url:
                return {"success": False, "error": "未找到下载链接"}

            import urllib.parse
            parsed = urllib.parse.urlparse(download_url)
            safe_url = f"{parsed.scheme}://{parsed.netloc}{urllib.parse.quote(parsed.path, safe='/:')}"

            import urllib.request
            req = urllib.request.Request(safe_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()

            filename = os.path.basename(download_url)
            filepath = dl_dir / filename

            # 重命名（如需，按 FILE_RENAME_MODE 配置）
            from app.utils.pinyin_util import build_rename_name
            rename_name = build_rename_name(filename)
            filepath = dl_dir / rename_name

            with open(filepath, "wb") as f:
                f.write(data)

            # 保存作者
            _save_author_to_progress(filepath.name, detected_author)

            return {"success": True, "filename": filepath.name,
                    "size": len(data), "renamed": rename_name != filename}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _save_author_to_progress(filename: str, author: str):
    """保存作者信息到进度文件。"""
    if not author or author == "未知作者":
        return
    stem = os.path.splitext(filename)[0]
    import json
    progress_path = settings.text_files_dir / ".legado_progress.json"
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
        if stem not in progress:
            progress[stem] = {}
        progress[stem]["author"] = author
        tmp = progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(progress_path)
    except Exception:
        pass

