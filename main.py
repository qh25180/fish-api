"""QHAPI — API 入口"""

import html as html_mod
import secrets
import string
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.security import request_token_ok, verify_token
from app.routers import novels, legado, search
from app.sources import source_a, source_b  # 注册 source 插件

app = FastAPI(
    title="QHAPI",
    description="QHAPI — 通用 API 服务\n\n"
    "当前提供文件列表浏览、章节解析、文本内容读取、远程文件下载等功能。",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ─── 检测默认口令并自动生成 ───────────────────────
if settings.api_token == "qhapi-token":
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    new_token = ''.join(secrets.choice(chars) for _ in range(8))
    try:
        with open(".env") as f:
            content = f.read()
        content = content.replace("API_TOKEN=qhapi-token",
                                  f"API_TOKEN={new_token}")
        with open(".env", "w") as f:
            f.write(content)
        settings.api_token = new_token
        print()
        print("=" * 60)
        print(f"⚠️  检测到默认口令，已自动生成新口令: {new_token}")
        print("   需口令的接口请携带 token 参数访问")
        print("=" * 60)
        print()
    except Exception as e:
        print(f"[警告] 无法写入 .env 文件（{e}），默认口令 qhapi-token 保持生效")

# CORS — 开放所有来源（局域网使用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Service-Worker-Allowed 头（允许 SW 从 /static/js/ 提升 scope 到 /） ──
from starlette.middleware.base import BaseHTTPMiddleware

class ServiceWorkerHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.endswith("sw.js"):
            response.headers["Service-Worker-Allowed"] = "/"
        return response

app.add_middleware(ServiceWorkerHeaderMiddleware)

# ─── Swagger 文档（默认关闭，DOCS_ENABLED=true 开启） ──
def _doc_token_ok(request) -> bool:
    """文档页 token 校验：支持 Authorization Bearer 与 Cookie。"""
    if not settings.api_token:
        return True
    return request_token_ok(request)


if settings.docs_enabled:
    from fastapi.openapi.docs import get_swagger_ui_html

    @app.get("/docs", include_in_schema=False)
    async def custom_docs(request: Request = None):
        if not _doc_token_ok(request):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="QHAPI",
        )

    @app.get("/openapi.json", include_in_schema=False)
    async def custom_openapi(request: Request = None):
        if not _doc_token_ok(request):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return app.openapi()

# 注册路由
app.include_router(novels.router)
app.include_router(legado.router)
app.include_router(search.router)

# ─── 静态资源（前端 CSS/JS，页面模板引用） ─────────
# main.py 位于项目根，static 位于 app/static/
_static_dir = Path(__file__).parent / "app" / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ─── 认证与页面入口 ────────────────────────────────
_LOGIN_STYLE = """
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: sans-serif; max-width: 400px; margin: 80px auto; padding: 0 20px; }
  h2 { font-size: 20px; text-align: center; }
  .box { border: 1px solid #ddd; padding: 24px; border-radius: 8px; background: #fafafa; }
  label { display: block; margin-bottom: 8px; font-weight: bold; }
  input[type=password] { width: 100%; padding: 10px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; font-size: 16px; }
  button { width: 100%; margin-top: 16px; padding: 10px; background: #007acc; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
  button:hover { background: #005999; }
  .msg { padding: 12px; border-radius: 4px; margin-bottom: 16px; text-align: center; }
  .msg.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
  .tip { color: #666; font-size: 13px; margin-top: 12px; text-align: center; }
</style>
"""


def _login_page_html(error: str = "") -> str:
    """登录页：输入 token，POST 到 /login 写入 Cookie。"""
    msg = f'<div class="msg error">❌ {html_mod.escape(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#007acc">
<link rel="manifest" href="/static/manifest.json">
<link rel="icon" type="image/png" href="/static/icons/icon-192.png">
<title>登录 - QHAPI</title>
{_LOGIN_STYLE}
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => {{
    navigator.serviceWorker.register('/static/js/sw.js', {{ scope: '/' }}).catch(() => {{}});
  }});
}}
</script>
</head>
<body>
<h2>🔐 登录</h2>
{msg}
<div class="box">
  <form method="post" action="/login">
    <label for="token">访问口令</label>
    <input type="password" name="token" id="token" placeholder="请输入访问口令" autofocus required>
    <button type="submit">进入</button>
  </form>
  <div class="tip">登录后即可访问全部功能</div>
</div>
</body>
</html>"""


@app.get("/login", include_in_schema=False, response_class=HTMLResponse)
async def login_page(request: Request = None):
    """登录页：已认证则跳转索引页 /api/v1/novels/pages，否则显示登录表单。"""
    if request_token_ok(request):
        return RedirectResponse(url="/api/v1/novels/pages", status_code=302)
    return HTMLResponse(content=_login_page_html())


@app.post("/login", include_in_schema=False, response_class=HTMLResponse)
async def login_submit(
    token: str = Form(""),
    next: str = Form("/api/v1/novels/pages"),
):
    """登录提交：验证 token，写入 Cookie，跳转到 next（默认索引页）。"""
    if not verify_token(token):
        return HTMLResponse(content=_login_page_html("口令不正确，请重试"), status_code=401)
    # 安全校验 next：仅允许站内相对路径
    if not next.startswith("/") or next.startswith("//"):
        next = "/api/v1/novels/pages"
    resp = RedirectResponse(url=next, status_code=302)
    resp.set_cookie("qhapi_token", token, httponly=False, samesite="lax")
    return resp


@app.get("/logout", include_in_schema=False)
async def logout():
    """退出登录：清除认证 Cookie，跳转到登录页。"""
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("qhapi_token", path="/")
    return resp


@app.get("/", include_in_schema=False)
async def root(request: Request = None):
    """API 根路径：未认证跳转 /login，已认证跳转索引页。"""
    if not request_token_ok(request):
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/api/v1/novels/pages", status_code=302)


@app.get("/health", tags=["root"])
async def health():
    """健康检查端点。"""
    return {"status": "ok"}


# ─── 直接启动（python main.py）───────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        timeout_keep_alive=settings.upload_timeout_seconds,
    )
