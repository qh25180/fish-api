"""从文件名和文件内容中提取书名、作者等元数据。"""

import re
from pathlib import Path
from typing import Optional


def extract_meta(filename: str, content_head: str = "") -> dict[str, str]:
    """从文件名（和可选的全文前 8KB）中提取书名和作者。

    返回:
        {"title": "书名", "author": "作者名"}
    """
    result = {"title": Path(filename).stem, "author": "未知作者"}

    # ── 优先级 1: 《书名》作者：xxx 或 《书名》- 作者 ──
    m = re.match(r"\u300a([^\u300b]+)\u300b\s*作者[：:]\s*(.+)", filename)
    if m:
        return {"title": m.group(1).strip(), "author": m.group(2).strip().replace(".txt", "").replace(".rar", "").strip()}

    m = re.match(r"\u300a([^\u300b]+)\u300b\s*[-—]\s*(.+)", filename)
    if m:
        return {"title": m.group(1).strip(), "author": m.group(2).strip().replace(".txt", "").replace(".rar", "").strip()}

    # ── 优先级 2: 书名 作者：xxx（无书名号） ──
    # 匹配: "书名 作者：xxx.txt" 或 "书名_作者：xxx.txt"
    m = re.match(r"(.+?)[\s_]+作者[：:]\s*(.+)", filename)
    if m:
        return {"title": m.group(1).strip(), "author": m.group(2).strip().replace(".txt", "").replace(".rar", "").strip()}

    # ── 优先级 3: 书名-作者.txt ──
    m = re.match(r"(.+?)[-_～~](.+)\.(txt|rar|zip)", filename)
    if m:
        title = m.group(1).strip()
        author = m.group(2).strip()
        # 排除明显不是作者名的部分
        if len(author) <= 20 and not re.match(r"^\d+$", author):
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
                author = m.group(1).strip().rstrip("，。；,.;")
                if author and len(author) <= 20:
                    return {"title": Path(filename).stem, "author": author}

    return result
