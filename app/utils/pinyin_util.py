"""中文转拼音工具（PascalCase 格式）。"""

import re
from typing import Optional

from app.config import settings


def filename_to_pinyin(original_name: str) -> str:
    """将中文文件名转为 PascalCase 拼音。

    示例:
        《示例文档》（整理版）.txt → ShiLiWenDang.txt
        示例.txt → ShiLi.txt
    """
    if not settings.file_rename_pinyin:
        return original_name

    from pypinyin import pinyin, Style

    # 分离扩展名
    name, ext = _split_ext(original_name)
    if not name:
        return original_name

    # 提取书名号内的内容
    m = re.search(r'《([^》]+)》', name)
    if m:
        name = m.group(1)

    # 清理无关字符（保留中文字符）
    name = re.sub(r'[^\u4e00-\u9fff\w]', '', name)

    if not name:
        return original_name

    # 转拼音
    py_list = pinyin(name, style=Style.NORMAL)
    words = [item[0].capitalize() for item in py_list if item and item[0].strip()]
    result = ''.join(words)

    if not result:
        return original_name

    return f"{result}{ext}"


def _split_ext(filename: str) -> tuple[str, str]:
    """分离文件名和扩展名。"""
    pos = filename.rfind(".")
    if pos == -1:
        return filename, ""
    return filename[:pos], filename[pos:]
