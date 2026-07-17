"""QHAPI — API 入口"""

import secrets
import string

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import novels, legado

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

# ─── 保护 Swagger 文档 ────────────────────────
if settings.api_token:
    from fastapi.openapi.docs import get_swagger_ui_html

    @app.get("/docs", include_in_schema=False)
    async def custom_docs(token: str | None = None):
        if not token or not secrets.compare_digest(token, settings.api_token):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return get_swagger_ui_html(
            openapi_url=f"/openapi.json?token={token}",
            title="QHAPI",
        )

    @app.get("/openapi.json", include_in_schema=False)
    async def custom_openapi(token: str | None = None):
        if not token or not secrets.compare_digest(token, settings.api_token):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return app.openapi()
else:
    from fastapi.openapi.docs import get_swagger_ui_html

    @app.get("/docs", include_in_schema=False)
    async def public_docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title="QHAPI")

    @app.get("/openapi.json", include_in_schema=False)
    async def public_openapi():
        return app.openapi()

# 注册路由
app.include_router(novels.router)
app.include_router(legado.router)


@app.get("/", tags=["root"])
async def root():
    """API 根路径，返回服务信息。"""
    docs_hint = "/docs?token=您的API_TOKEN" if settings.api_token else "/docs"
    return {
        "service": "QHAPI Service",
        "version": "1.0.0",
        "docs": docs_hint,
    }


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
