"""QHAPI — API 入口"""

import html as html_mod
import secrets
import string
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.security import request_token_ok, verify_token
from app.routers import novels, legado, search, tts
from app.sources import source_a, source_b  # 注册 source 插件
from app.services import meta_cache  # 文件指纹缓存

# ─── 登录失败限流（内存计数） ───────────────────────
_login_fail_times: dict[str, list[float]] = defaultdict(list)
_login_fail_lock = __import__("threading").Lock()

# 启动时加载元数据/章节缓存（容器重启不丢，冷启动更快）
meta_cache.load()

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
    new_token = secrets.token_urlsafe(16)  # 22 字符，高熵
    try:
        env_path = Path(".env")
        content = env_path.read_text(encoding="utf-8")
        content = content.replace("API_TOKEN=qhapi-token",
                                  f"API_TOKEN={new_token}")
        # 原子写：先写临时文件再替换（防崩溃截断 .env）
        tmp_path = env_path.with_suffix(".env.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(env_path)
        settings.api_token = new_token
        # 安全：不打印明文口令，仅提示管理员查看 .env
        print()
        print("=" * 60)
        print("⚠️  检测到默认口令，已自动生成新口令并写入 .env")
        print("   请查看 .env 中的 API_TOKEN 字段获取新口令")
        print("=" * 60)
        print()
    except Exception as e:
        print(f"[警告] 无法写入 .env 文件（{e}），默认口令 qhapi-token 保持生效")
        print("[安全] 请立即手动修改 .env 中的 API_TOKEN，否则服务无认证可访问")

# CORS — 白名单来源（可经 ALLOWED_ORIGINS 配置，逗号分隔；默认放行本服务域名与局域网 IP）
_allow_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()] if settings.allowed_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 安全响应头（CSP / X-Content-Type-Options / X-Frame-Options / HSTS） ──
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # 不缓存 sw.js/manifest（PWA 更新敏感）
        if request.url.path.endswith(("sw.js", "manifest.json")):
            response.headers["Cache-Control"] = "no-cache"
        # 安全头（仅对页面/API，静态资源由 nginx 处理）
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "media-src 'self' blob:; connect-src 'self'; frame-ancestors 'self'",
        )
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ─── Service-Worker-Allowed 头（允许 SW 从 /static/js/ 提升 scope 到 /） ──
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
app.include_router(tts.router)

# ─── 静态资源（前端 CSS/JS，页面模板引用） ─────────
# main.py 位于项目根，static 位于 app/static/
_static_dir = Path(__file__).parent / "app" / "static"

class _NoCacheStaticFiles(StaticFiles):
    """静态资源：协商缓存（ETag 校验），文件变更立即生效，避免 CDN 强缓存旧版。"""
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

if _static_dir.exists():
    app.mount("/static", _NoCacheStaticFiles(directory=str(_static_dir)), name="static")


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
    """登录页：已认证则返回 200 + JS 立即跳转（避免 PWA/WebView 启动时 302 卡住）。"""
    if request_token_ok(request):
        return HTMLResponse(content="""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>QHAPI</title>
<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f5f1eb;color:#666;}</style>
<script>window.location.replace('/api/v1/novels/pages');</script>
</head><body><div>正在进入…</div></body></html>""")
    return HTMLResponse(content=_login_page_html())


@app.post("/login", include_in_schema=False, response_class=HTMLResponse)
async def login_submit(
    token: str = Form(""),
    next: str = Form("/api/v1/novels/pages"),
    request: Request = None,
):
    """登录提交：验证 token，写入 Cookie，跳转到 next（默认索引页）。

    安全：登录失败限流（每 IP 每分钟 N 次），next 严格校验防 open redirect。
    """
    # 登录失败限流（简单内存计数，每 IP 每分钟上限）
    client_ip = request.client.host if request and request.client else "unknown"
    now = time.time()
    with _login_fail_lock:
        _login_fail_times[client_ip] = [t for t in _login_fail_times[client_ip] if now - t < 60]
        if len(_login_fail_times[client_ip]) >= settings.login_max_fail_per_minute:
            return HTMLResponse(
                content=_login_page_html("尝试次数过多，请一分钟后再试"),
                status_code=429,
            )

    # 定期清理：空条目移除 + 总量上限（防内存无限增长）
    with _login_fail_lock:
        for ip in [k for k, v in _login_fail_times.items() if not v]:
            del _login_fail_times[ip]
        if len(_login_fail_times) > 10000:
            # 极端情况：清掉最旧的一半
            for ip in list(_login_fail_times.keys())[: len(_login_fail_times) // 2]:
                del _login_fail_times[ip]

    if not verify_token(token):
        with _login_fail_lock:
            _login_fail_times[client_ip].append(now)
        return HTMLResponse(content=_login_page_html("口令不正确，请重试"), status_code=401)

    # 登录成功：清除该 IP 的失败计数（防正确口令被历史失败锁死）
    with _login_fail_lock:
        _login_fail_times.pop(client_ip, None)

    # 安全校验 next：仅允许站内相对路径（拒绝 //、/\\、含 scheme 的绝对 URL）
    try:
        parts = urlsplit(next)
        safe_next = (
            parts.scheme == ""
            and parts.netloc == ""
            and next.startswith("/")
            and "\\" not in next
            and "\r" not in next
            and "\n" not in next
        )
    except ValueError:
        safe_next = False
    if not safe_next:
        next = "/api/v1/novels/pages"

    resp = RedirectResponse(url=next, status_code=302)
    # 登录有效期：TOKEN_EXPIRE_DAYS 天（0 = 会话级，关闭浏览器失效）
    # 安全：HttpOnly 防 XSS 读 Cookie；HTTPS 下 Secure
    max_age = settings.token_expire_days * 86400 if settings.token_expire_days > 0 else None
    secure = request.url.scheme == "https" if request else False
    resp.set_cookie("qhapi_token", token, httponly=True, samesite="lax", max_age=max_age, secure=secure)
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
        # 信任反向代理（nginx）的 X-Forwarded-For / X-Forwarded-Proto，
        # 使登录限流按真实客户端 IP 生效、HTTPS 下 Cookie 正确加 Secure。
        # 生产环境由 nginx 反代，来源 IP 固定为 nginx 容器；仅信任该来源。
        forwarded_allow_ips=settings.proxy_trusted_ips or None,
    )
