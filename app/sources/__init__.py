"""Source 插件基类与注册表。

每个 Source 插件继承 BaseSource，实现 search() 和 download() 方法。
通过 register() 注册后，可在 /api/v1/search 等路由中统一调用。
"""

from abc import ABC, abstractmethod
from typing import Any


_source_registry: dict[str, type["BaseSource"]] = {}


def register(name: str):
    """装饰器：注册 Source 类到全局注册表。"""
    def decorator(cls):
        _source_registry[name] = cls
        return cls
    return decorator


def get_source(name: str) -> "BaseSource | None":
    """按名称获取 Source 实例。"""
    cls = _source_registry.get(name)
    if cls is None:
        return None
    return cls()


def list_sources() -> list[dict[str, str]]:
    """列出所有已注册的可用 Source。"""
    return [
        {"name": name, "title": cls.title, "description": cls.description}
        for name, cls in _source_registry.items()
    ]


class BaseSource(ABC):
    """Source 插件基类。"""

    title: str = ""
    description: str = ""

    @abstractmethod
    def search(self, keyword: str) -> list[dict[str, Any]]:
        """搜索书籍，返回列表。每项应包含 id, title, size_hint 等字段。"""
        ...

    @abstractmethod
    def get_download_url(self, book_id: str) -> str:
        """根据书籍 ID 获取下载 URL。"""
        ...

    def get_detail(self, book_id: str) -> dict[str, Any]:
        """获取书籍详情（可选重载）。"""
        return {"id": book_id}
