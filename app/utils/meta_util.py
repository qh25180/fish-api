"""从文件名和文件内容中提取书名、作者等元数据。"""

import re
from pathlib import Path
from typing import Optional


# 广告/噪声关键词：提取到含这些词、或长度异常的“作者”视为无效
_JUNK_WORDS = ("下载", "txt", "精校", "校对", "全集", "全本", "完整版", "知轩藏书",
               "藏尽", "小说", "电子书", "书库", "站", "网盘")


def _clean_author(author: str) -> str:
    """清理作者字符串：去 HTML 标签、去噪、限制长度。

    无效时返回空字符串，由调用方决定是否回退到“未知作者”。
    """
    author = re.sub(r"<[^>]+>", "", author)          # 去 HTML 标签
    author = re.sub(r"&[a-zA-Z#0-9]+;", "", author)  # 去 HTML 实体
    author = author.strip().strip("，。；,.;|-_~ ")
    if not author:
        return ""
    if len(author) > 20:
        return ""
    if any(k in author.lower() for k in _JUNK_WORDS):
        return ""
    return author


def extract_meta(filename: str, content_head: str = "") -> dict[str, str]:
    """从文件名（和可选的全文前 8KB）中提取书名和作者。

    返回:
        {"title": "书名", "author": "作者名"}
    """
    result = {"title": Path(filename).stem, "author": "未知作者"}

    # ── 优先级 1: 《书名》作者：xxx 或 《书名》- 作者 ──
    m = re.match(r"\u300a([^\u300b]+)\u300b\s*作者[：:]\s*(.+)", filename)
    if m:
        return {"title": m.group(1).strip(), "author": _clean_author(m.group(2).replace(".txt", "").replace(".rar", "").strip()) or "未知作者"}

    m = re.match(r"\u300a([^\u300b]+)\u300b\s*[-—]\s*(.+)", filename)
    if m:
        return {"title": m.group(1).strip(), "author": _clean_author(m.group(2).replace(".txt", "").replace(".rar", "").strip()) or "未知作者"}

    # ── 优先级 1.5: 《书名》（备注...）作者：xxx  —— 常见于精校版/校对版文件名 ──
    m = re.match(r"\u300a([^\u300b]+)\u300b[^-\n]{0,60}?作者[：:]\s*(.+)", filename)
    if m:
        author = _clean_author(m.group(2).replace(".txt", "").replace(".rar", "").strip())
        if author:
            return {"title": m.group(1).strip(), "author": author}
        # 作者无效（可能含广告）时退回书名，作者保持未知
        return {"title": m.group(1).strip(), "author": "未知作者"}

    # ── 优先级 2: 书名 作者：xxx（无书名号） ──
    # 匹配: "书名 作者：xxx.txt" 或 "书名_作者：xxx.txt"
    m = re.match(r"(.+?)[\s_]+作者[：:]\s*(.+)", filename)
    if m:
        return {"title": m.group(1).strip(), "author": _clean_author(m.group(2).replace(".txt", "").replace(".rar", "").strip()) or "未知作者"}

    # ── 优先级 3: 书名-作者.txt ──
    m = re.match(r"(.+?)[-_～~](.+)\.(txt|rar|zip)", filename)
    if m:
        title = m.group(1).strip()
        author = _clean_author(m.group(2).strip())
        if author:
            return {"title": title, "author": author}
        return {"title": title, "author": "未知作者"}

    # ── 优先级 4: 从文件内容头部提取 ──
    if content_head:
        # 匹配各种作者声明模式
        author_patterns = [
            r"作者[：:]\s*(.+)",
            r"作者\s*[:：]\s*(.+?)[\r\n]",
            r"【作者】\s*(.+?)[】\r\n]",
        ]
        for pat in author_patterns:
            m = re.search(pat, content_head)
            if m:
                author = _clean_author(m.group(1).strip().rstrip("，。；,.;"))
                if author:
                    return {"title": Path(filename).stem, "author": author}

    return result
