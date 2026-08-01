"""文件名重命名工具（支持多种模式）。

模式（由 FILE_RENAME_MODE 配置）:
    0 = 不重命名（默认）
    1 = 小说名拼音（PascalCase）
    2 = 中文小说名
    3 = 中文小说名-中文作者
"""

import re
from typing import Optional

from app.config import settings


def _clean_filename_part(text: str) -> str:
    """清理文件名组成部分：去掉路径非法字符、折叠空白、去首尾空格。"""
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _mode() -> int:
    """确定当前生效的重命名模式（兼容旧 FILE_RENAME_PINYIN 配置）。"""
    mode = settings.file_rename_mode
    if mode == 0 and settings.file_rename_pinyin:
        return 1  # 旧配置 FILE_RENAME_PINYIN=true 等价于模式1（拼音）
    return mode


def build_rename_name(original_name: str) -> str:
    """按当前配置的重命名模式生成新文件名；不重命名时返回原文件名。"""
    mode = _mode()
    if mode == 0:
        return original_name

    # 分离扩展名
    name, ext = _split_ext(original_name)
    if not name:
        return original_name

    if mode == 1:
        return _to_pinyin(name, original_name, ext)

    # 模式 2/3 需要书名与作者
    from app.utils.meta_util import extract_meta
    meta = extract_meta(original_name)
    title = _clean_filename_part(meta["title"])
    author = _clean_filename_part(meta["author"])
    if not title:
        return original_name

    if mode == 3 and author and author != "未知作者":
        return f"{title}-{author}{ext}"
    return f"{title}{ext}"


def _to_pinyin(name: str, original_name: str, ext: str) -> str:
    """模式1：书名转 PascalCase 拼音（自动分离作者）。"""
    from pypinyin import pinyin, Style

    # 提取书名号内的内容（优先）
    m = re.search(r'\u300a([^\u300b]+)\u300b', name)
    if m:
        base = m.group(1)
    else:
        # 尝试用 extract_meta 分离作者
        from app.utils.meta_util import extract_meta
        meta = extract_meta(original_name)
        base = meta["title"]

    # 清理无关字符（保留中文字符和字母数字）
    base = re.sub(r'[^\u4e00-\u9fff\w]', '', base)
    if not base:
        return original_name

    # 转拼音
    py_list = pinyin(base, style=Style.NORMAL)
    words = [item[0].capitalize() for item in py_list if item and item[0].strip()]
    result = ''.join(words)
    if not result:
        return original_name

    return f"{result}{ext}"


def filename_to_pinyin(original_name: str) -> str:
    """旧接口：按模式1（拼音）重命名；未启用重命名则返回原名。"""
    if _mode() == 0:
        return original_name
    name, ext = _split_ext(original_name)
    return _to_pinyin(name, original_name, ext)


def _split_ext(filename: str) -> tuple[str, str]:
    """分离文件名和扩展名。"""
    pos = filename.rfind(".")
    if pos == -1:
        return filename, ""
    return filename[:pos], filename[pos:]

