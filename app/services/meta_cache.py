"""文件指纹元数据缓存层。

核心思路：用文件的 (mtime_ns, size) 作为指纹，文件未变则直接复用
之前解析的结果（章节数、作者、首次章节标题、章节列表），避免每次请求
都读全文/读文件头重新解析。

两级缓存（均落盘，容器重启不丢）：
1. 元数据缓存（.meta_cache.json）：每本书的 est_chapters / author /
   chapter_count / first_chapter_title
2. 章节缓存（.chapters_cache.json）：每本书的完整章节列表（chapters）

指纹变化（文件增删改、重命名、上传覆盖）→ 对应条目自动失效重算。
"""

import json
import logging
import threading
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 内存缓存
_meta_cache: dict = {}          # filename -> meta dict
_chapters_cache: dict = {}      # filename -> {fp, chapters}
_lock = threading.Lock()        # 并发写保护


def _meta_file() -> Path:
    return settings.text_files_dir / ".meta_cache.json"


def _chapters_file() -> Path:
    return settings.text_files_dir / ".chapters_cache.json"


def fingerprint(path: Path) -> tuple[int, int]:
    """文件指纹：(mtime_ns, size)。纳秒级 stat，无磁盘内容读取。"""
    st = path.stat()
    return st.st_mtime_ns, st.st_size


# ─── 加载 / 保存 ────────────────────────────────────

def load():
    """启动时加载两个缓存文件到内存（损坏则忽略，重新构建）。"""
    global _meta_cache, _chapters_cache
    for cache_name, path, dest in (
        ("meta", _meta_file(), _meta_cache),
        ("chapters", _chapters_file(), _chapters_cache),
    ):
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if cache_name == "meta":
                        _meta_cache = data
                    else:
                        _chapters_cache = data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("缓存文件损坏，忽略重建: %s (%s)", path, e)


def _save_meta():
    """原子写元数据缓存。"""
    try:
        path = _meta_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(_meta_cache, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError as e:
        logger.warning("写入元数据缓存失败: %s", e)


def _save_chapters():
    """原子写章节缓存。"""
    try:
        path = _chapters_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(_chapters_cache, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError as e:
        logger.warning("写入章节缓存失败: %s", e)


# ─── 元数据缓存 ─────────────────────────────────────

def get_meta(filename: str, fp: tuple[int, int] | None = None):
    """获取单本书的元数据缓存。指纹不匹配（文件已变）返回 None。

    fp 为 None 时不校验指纹（调用方已确认未变），直接返回。
    """
    entry = _meta_cache.get(filename)
    if not entry:
        return None
    if fp is not None and entry.get("fp") != list(fp):
        return None
    return entry


def set_meta(filename: str, fp: tuple[int, int], est_chapters: int, author: str,
             chapter_count: int | None = None, first_chapter_title: str = "") -> None:
    """写入单本书的元数据缓存（内存 + 落盘）。"""
    with _lock:
        entry = {
            "fp": list(fp),
            "est_chapters": est_chapters,
            "author": author,
            "chapter_count": chapter_count,
            "first_chapter_title": first_chapter_title,
        }
        # 保留已有 chapter_count/first_chapter_title（可能由章节解析补全）
        old = _meta_cache.get(filename, {})
        if chapter_count is None and old.get("chapter_count") is not None:
            entry["chapter_count"] = old["chapter_count"]
        if not first_chapter_title and old.get("first_chapter_title"):
            entry["first_chapter_title"] = old["first_chapter_title"]
        _meta_cache[filename] = entry
    _save_meta()


# ─── 章节缓存 ───────────────────────────────────────

def get_chapters(filename: str, fp: tuple[int, int] | None = None):
    """获取单本书的章节列表缓存。指纹不匹配返回 None。"""
    entry = _chapters_cache.get(filename)
    if not entry:
        return None
    if fp is not None and entry.get("fp") != list(fp):
        return None
    return entry.get("chapters")


def set_chapters(filename: str, fp: tuple[int, int], chapters: list) -> None:
    """写入单本书的章节列表缓存（内存 + 落盘）。"""
    with _lock:
        _chapters_cache[filename] = {"fp": list(fp), "chapters": chapters}
    _save_chapters()


# ─── 失效 ───────────────────────────────────────────

def invalidate(filename: str | None = None) -> None:
    """失效缓存。

    filename 为 None → 全部失效（如批量重命名）；否则失效单条。
    """
    global _meta_cache, _chapters_cache
    with _lock:
        if filename is None:
            _meta_cache = {}
            _chapters_cache = {}
        else:
            _meta_cache.pop(filename, None)
            _chapters_cache.pop(filename, None)
    # 落盘清理
    try:
        if filename is None:
            _meta_file().unlink(missing_ok=True)
            _chapters_file().unlink(missing_ok=True)
        else:
            _save_meta()
            _save_chapters()
    except OSError:
        pass
