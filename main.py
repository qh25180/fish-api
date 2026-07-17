"""QHAPI — Novel Reading API 入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import novels

app = FastAPI(
    title="QHAPI - QH API",
    description="API 服务\n\n"
    "提供文件列表浏览、内容解析、文本内容读取、远程文件下载等功能。",
    version="1.0.0",
)

# CORS — 允许所有来源（开发阶段）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(novels.router)


@app.get("/", tags=["root"])
async def root():
    """API 根路径，返回服务信息。"""
    return {
        "service": "QHAPI Novel Reading API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["root"])
async def health():
    """健康检查端点。"""
    return {"status": "ok"}
