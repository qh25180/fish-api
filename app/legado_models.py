"""Legado HTTP API 兼容数据模型。

参考 Dicarbene/yuedu_vscode_dicarbene 的 types.ts 定义。
"""

from pydantic import BaseModel
from typing import Generic, TypeVar, Optional

T = TypeVar("T")


class LegadoApiResponse(BaseModel, Generic[T]):
    """Legado 统一 API 响应包装。

    所有 Legado 兼容端点必须返回此格式：
    { "isSuccess": true, "errorMsg": "", "data": ... }
    """
    isSuccess: bool = True
    errorMsg: str = ""
    data: T


# ─── Book（书架上的书）───────────────────────────────────

class LegadoBook(BaseModel):
    """映射自文件信息，兼容 Legado Book 接口。"""
    name: str
    author: str
    bookUrl: str
    tocUrl: str = ""
    origin: str = ""
    originName: str = "本地文件"
    coverUrl: Optional[str] = None
    intro: Optional[str] = None
    charset: Optional[str] = None
    type: int = 0
    group: int = 0
    latestChapterTitle: Optional[str] = None
    latestChapterTime: int = 0
    lastCheckTime: int = 0
    lastCheckCount: int = 0
    totalChapterNum: int = 0
    durChapterTitle: Optional[str] = None
    durChapterIndex: int = 0
    durChapterPos: int = 0
    durChapterTime: int = 0
    canUpdate: bool = False
    order: int = 0
    originOrder: int = 0
    kind: Optional[str] = None
    wordCount: Optional[str] = None
    variable: Optional[str] = None
    customTag: Optional[str] = None
    customCoverUrl: Optional[str] = None


# ─── BookChapter（章节）───────────────────────────────────

class LegadoChapter(BaseModel):
    """映射自章节信息，兼容 Legado BookChapter 接口。"""
    url: str
    title: str
    isVolume: bool = False
    baseUrl: str = ""
    bookUrl: str
    index: int
    isVip: bool = False
    isPay: bool = False
    resourceUrl: Optional[str] = None
    tag: Optional[str] = None
    wordCount: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None
    startFragmentId: Optional[str] = None
    endFragmentId: Optional[str] = None
    variable: Optional[str] = None


# ─── BookProgress（阅读进度）──────────────────────────────

class LegadoBookProgress(BaseModel):
    """保存阅读进度的请求体。"""
    name: str
    author: str
    durChapterIndex: int = 0
    durChapterPos: int = 0
    durChapterTime: int = 0
    durChapterTitle: str = ""


# ─── ChapterProgress（按章节切换进度）────────────────────

class LegadoChapterProgress(BaseModel):
    """按章节标题或序号切换阅读进度的请求体。"""
    bookUrl: str
    chapter: str
