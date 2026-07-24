"""源A — 搜索并下载文档。"""

import re
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.sources import BaseSource, register


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
        pat = re.compile(r'href="[^"]*/book/(\d+)\.html"[^>]*>.*?\u300a([^\u300b]+)\u300b', re.DOTALL)
        for bid, title in pat.findall(html_content):
            if bid not in seen:
                seen.add(bid)
                results.append({
                    "id": bid,
                    "title": f"\u300a{title}\u300b",
                    "author": "\u672a\u77e5\u4f5c\u8005",
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
            # 提取作者
            author_match = re.search(r"作者[：:]\s*(.+?)[\r\n]", html_content)
            if author_match:
                author = author_match.group(1).strip().rstrip("，；,;")
        return {"id": book_id, "title": title, "author": author, "download_url": download_url}

    def get_download_url(self, book_id: str) -> str:
        return self.get_detail(book_id).get("download_url", "")
