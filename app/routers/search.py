"""搜索 API 路由 — 搜索书籍 + 浏览器搜索页面。"""

import json
import os
import secrets
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.sources import get_source, list_sources

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.get("/sources")
async def sources_list():
    """列出可用搜索源。"""
    return list_sources()


@router.get("/search")
async def search_books(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    source: str = Query("a", description="搜索源名称（a/b/auto）"),
):
    """搜索书籍。"""
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
):
    """获取书籍详情和下载链接。"""
    s = get_source(source)
    if not s:
        raise HTTPException(status_code=400, detail=f"未知搜索源: {source}")
    detail = s.get_detail(book_id)
    return detail


# ─── 搜索页面 ───────────────────────────────────────

@router.get("/search-page", response_class=HTMLResponse, include_in_schema=False)
async def search_page(
    token: str | None = Query(None),
):
    """浏览器搜索页面。"""
    t = quote(token, safe="") if token else ""

    sources_html = ""
    for src in list_sources():
        sources_html += f'<option value="{src["name"]}">{src["title"]}</option>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>书籍搜索</title>
<style>
  body {{ font-family: sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; }}
  .search-box {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .search-box input[type=text] {{ flex: 1; padding: 10px; font-size: 16px; border: 1px solid #ddd; border-radius: 4px; }}
  .search-box select {{ padding: 10px; border: 1px solid #ddd; border-radius: 4px; }}
  .search-box button {{ padding: 10px 24px; background: #007acc; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }}
  .search-box button:hover {{ background: #005999; }}
  .result {{ border: 1px solid #eee; padding: 14px; margin-bottom: 8px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }}
  .result-title {{ font-size: 15px; font-weight: bold; }}
  .result-size {{ font-size: 13px; color: #888; }}
  .result .btn {{ padding: 6px 16px; background: #28a745; color: #fff; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; font-size: 13px; }}
  .result .btn:hover {{ background: #1e7e34; }}
  .msg {{ padding: 12px; border-radius: 4px; margin: 12px 0; }}
  .msg.info {{ background: #d1ecf1; color: #0c5460; }}
  .msg.error {{ background: #f8d7da; color: #721c24; }}
  .msg.success {{ background: #d4edda; color: #155724; }}
  #status {{ margin-top: 12px; }}
</style>
</head>
<body>
<div style="margin-bottom:12px"><a href="/api/v1/novels/pages?token={t}" style="color:#007acc;text-decoration:none;font-size:14px;">← 返回索引</a></div>
<h2>[书籍搜索]</h2>
<div class="search-box">
  <input type="text" id="keyword" placeholder="输入书名或作者关键词" onkeydown="if(event.key===\\'Enter\\') search()">
  <select id="sourceSelect">{sources_html}</select>
  <button onclick="search()">搜索</button>
</div>
<div id="status"></div>
<div id="results"></div>

<script>
var TOKEN = "{t}";

function search() {{
  var kw = document.getElementById('keyword').value.trim();
  if (!kw) return;
  var src = document.getElementById('sourceSelect').value;
  var status = document.getElementById('status');
  var results = document.getElementById('results');
  status.innerHTML = '<div class="msg info">🔍 搜索中...</div>';
  results.innerHTML = '';

  var url = '/api/v1/search?q=' + encodeURIComponent(kw) + '&source=' + src;
  fetch(url).then(function(r) {{ return r.json(); }}).then(function(d) {{
    if (d.total === 0) {{
      status.innerHTML = '<div class="msg error">❌ 未找到匹配结果</div>';
      return;
    }}
    status.innerHTML = '<div class="msg success">✅ 共找到 ' + d.total + ' 个结果</div>';
    var html = '';
    d.results.forEach(function(item) {{
      var size = item.size_hint ? ' (' + item.size_hint + ')' : '';
      var srcName = item.source_title || item.source;
      html += '<div class="result">' +
        '<div><div class="result-title">' + item.title + '</div>' +
        '<div class="result-size">' + srcName + size + '</div></div>' +
        '<button class="btn" onclick="downloadBook(\\'' + item.id + '\\',\\'' + item.source + '\\',this)">下载</button>' +
        '</div>';
    }});
    results.innerHTML = html;
  }}).catch(function(err) {{
    status.innerHTML = '<div class="msg error">❌ 请求失败: ' + err.message + '</div>';
  }});
}}

function downloadBook(bookId, source, btn) {{
  btn.disabled = true;
  btn.textContent = '下载中...';
  var url = '/api/v1/books/download?book_id=' + encodeURIComponent(bookId) + '&source=' + encodeURIComponent(source) + (TOKEN ? '&token=' + encodeURIComponent(TOKEN) : '');
  fetch(url).then(function(r) {{ return r.json(); }}).then(function(d) {{
    if (d.success) {{
      btn.textContent = '✅ 成功';
      btn.style.background = '#6c757d';
    }} else {{
      btn.textContent = '❌ ' + (d.error || '失败');
      btn.disabled = false;
    }}
  }}).catch(function() {{
    btn.textContent = '❌ 网络错误';
    btn.disabled = false;
  }});
}}
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ─── 下载书籍（通过搜索源） ────────────────────────

@router.get("/books/download")
async def download_book(
    book_id: str = Query(..., description="书籍 ID"),
    source: str = Query("a", description="搜索源名称"),
    token: str | None = Query(None, description="访问口令"),
):
    """通过搜索源下载书籍到 novels 目录。"""
    # Token 验证
    if settings.api_token:
        if not token or not secrets.compare_digest(token, settings.api_token):
            return {"success": False, "error": "无效的访问口令"}

    s = get_source(source)
    if not s:
        return {"success": False, "error": f"未知搜索源: {source}"}

    dl_dir = settings.text_files_dir
    dl_dir.mkdir(parents=True, exist_ok=True)

    try:
        if source == "b":
            # 源B需要下载+解压
            result_path = s.download_and_extract(book_id, str(dl_dir))
            if result_path:
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

            # 重命名（如需）
            from app.utils.pinyin_util import filename_to_pinyin
            pinyin_name = filename_to_pinyin(filename)
            filepath = dl_dir / pinyin_name

            with open(filepath, "wb") as f:
                f.write(data)

            return {"success": True, "filename": filepath.name,
                    "size": len(data), "renamed": pinyin_name != filename}

    except Exception as e:
        return {"success": False, "error": str(e)}

