"""静态资源版本化工具：给 JS/CSS 引用加版本参数，避免 CDN 缓存旧版。"""

import hashlib
from pathlib import Path

# 静态资源根目录
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _asset_hash(path: str) -> str:
    """计算静态资源内容的短 hash（文件内容变化 → hash 变化 → 缓存失效）。"""
    try:
        base = _STATIC_DIR.resolve()
        f = (base / path.lstrip("/")).resolve()
        # 安全：必须位于静态目录内（防 ../ 越界读取）
        f.relative_to(base)
        data = f.read_bytes()
        return hashlib.md5(data).hexdigest()[:8]
    except (OSError, ValueError):
        return "0"


def asset_url(path: str) -> str:
    """返回带版本参数的静态资源 URL：/static/js/search.js?v=ab12cd34"""
    return f"/static/{path.lstrip('/')}?v={_asset_hash(path)}"


def register_asset_helper(templates) -> None:
    """把 asset_url 注册为模板全局函数（Jinja2Templates）。"""
    templates.env.globals["asset"] = asset_url
