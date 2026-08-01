"""源A — 搜索并下载文档。"""

import re
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.sources import BaseSource, register
from app.utils.meta_util import _clean_author


@register("a")
class SourceA(BaseSource):
    title = "源A"
    description = "搜索并获取文档下载链接"

    def _base(self) -> str:
        return settings.source_a_url

    def _detail_url(self, book_id: str) -> str:
        return f"{self._base()}/book/{book_id}.html"

    def _search_url(self, keyword: str) -> str:
        return f"{self._base()}/search?q={urllib.parse.quote(keyword)}"

    def _fetch(self, url: str) -> str | None:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    def search(self, keyword: str) -> list[dict[str, Any]]:
        if not settings.source_a_enabled or not settings.source_a_url:
            return []

        html_content = self._fetch(self._search_url(keyword))
        if not html_content:
            return []

        results = []
        seen = set()

        # 按结果块切分（兼容 Angular tile / li / tr 结构），再在块内提取 id、书名、作者
        blocks = re.split(r"</(?:li|tr|mio-tile|article)>", html_content)
        for block in blocks:
            m = re.search(r'href="[^"]*/book/(\d+)\.html"', block)
            if not m:
                continue
            bid = m.group(1)
            if bid in seen:
                continue
            seen.add(bid)

            tm = re.search(r'\u300a([^\u300b]+)\u300b', block)
            title = tm.group(1) if tm else f"ID:{bid}"

            author = "未知作者"
            am = re.search(r"作者[：:]\s*([^<]{1,40}?)(?:<|[\r\n])", block)
            if am:
                clean = _clean_author(am.group(1).strip().rstrip("，；,;"))
                if clean:
                    author = clean

            results.append({
                "id": bid,
                "title": f"\u300a{title}\u300b",
                "author": author,
                "source": "a",
            })

        # 兜底：块解析失败时用宽松 DOTALL 正则仅提取书名
        if not results:
            pat = re.compile(r'href="[^"]*/book/(\d+)\.html"[^>]*>.*?\u300a([^\u300b]+)\u300b', re.DOTALL)
            for bid, title in pat.findall(html_content):
                if bid not in seen:
                    seen.add(bid)
                    results.append({
                        "id": bid,
                        "title": f"\u300a{title}\u300b",
                        "author": "未知作者",
                        "source": "a",
                    })
        return results[:30]

    def get_detail(self, book_id: str) -> dict[str, Any]:
        html_content = self._fetch(self._detail_url(book_id))
        title = f"ID:{book_id}"
        author = "未知作者"
        download_url = ""
        if html_content:
            urls = re.findall(r'https://download\.[^/"\']+[^"\'<>]+', html_content)
            if urls:
                download_url = urls[0]
            m = re.search(r'\u300a([^\u300b]+)\u300b', html_content)
            if m:
                title = f"\u300a{m.group(1)}\u300b"

            # 提取作者：优先 <title>（结构稳定），其次正文；均需清洗广告与 HTML 标签
            author = self._extract_author(html_content)

        return {"id": book_id, "title": title, "author": author, "download_url": download_url}

    def _extract_author(self, html_content: str) -> str:
        """从详情页 HTML 中提取作者，排除广告与 HTML 标签噪声。"""
        candidates = []

        # 1) <title> 中提取：《书名》作者：xxx_xxx下载站
        m = re.search(r"<title>([^<]*)</title>", html_content)
        if m:
            am = re.search(r"作者[：:]\s*([^<_\u300a]{1,30})", m.group(1))
            if am:
                candidates.append(am.group(1))

        # 2) 正文中常见位置：作者：xxx（不含 < 标签与过长文本）
        for pat in (
            r"作者[：:]\s*([^<]{1,30}?)(?:<|[\r\n])",
            r"作者[：:]\s*([^<]{1,30}?)(?:&nbsp;|<|[\r\n])",
        ):
            m = re.search(pat, html_content)
            if m:
                candidates.append(m.group(1))

        for cand in candidates:
            clean = _clean_author(cand.strip().rstrip("，；,;"))
            if clean:
                return clean
        return "未知作者"

    def get_download_url(self, book_id: str) -> str:
        return self.get_detail(book_id).get("download_url", "")
