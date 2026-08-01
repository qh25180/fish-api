"""统一认证层：多通道 token 提取与验证。

支持通道（任一匹配即可）：
    1. Authorization: Bearer <token>   —— 浏览器 JS 与外部工具（推荐）
    2. Cookie: qhapi_token=<token>      —— 页面间跳转与表单提交（URL 干净）
    3. 表单字段 token                   —— 由各路由的 Form 参数自行处理

注意：URL 查询参数 ?token= 与路径入口 /p/{token} 均已移除，
浏览器通过 /login 页面输入口令完成认证（写入 Cookie）。
"""

import secrets

from fastapi import HTTPException, Request


def collect_tokens(request: Request) -> list[str]:
    """收集请求中所有 token 候选（Bearer / Cookie）。"""
    tokens: list[str] = []

    # 1. Authorization: Bearer
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        t = auth[7:].strip()
        if t:
            tokens.append(t)

    # 2. Cookie: qhapi_token
    cookie = request.cookies.get("qhapi_token")
    if cookie:
        tokens.append(cookie)

    return tokens


def extract_token(request: Request) -> str | None:
    """返回第一个 token 候选（兼容旧调用）。"""
    tokens = collect_tokens(request)
    return tokens[0] if tokens else None


def verify_token(token: str | None) -> bool:
    """恒定时间比较 token 是否匹配。API_TOKEN 为空时视为通过。"""
    from app.config import settings
    if not settings.api_token:
        return True
    if not token:
        return False
    return secrets.compare_digest(token, settings.api_token)


def request_token_ok(request: Request) -> bool:
    """请求自带通道（Bearer / Query / Cookie）任一有效即通过。"""
    from app.config import settings
    if not settings.api_token:
        return True
    return any(verify_token(t) for t in collect_tokens(request))


def check_api_token(request: Request) -> None:
    """FastAPI 依赖：非 Legado 接口统一验证（API_TOKEN 配置时强制）。"""
    from app.config import settings
    if settings.api_token and not request_token_ok(request):
        raise HTTPException(status_code=403, detail="无效的访问口令")


def token_for_url(request: Request, token: str | None = None) -> str:
    """供页面渲染：返回当前请求携带的有效 token（用于注入前端 JS）。"""
    return token or extract_token(request) or ""
