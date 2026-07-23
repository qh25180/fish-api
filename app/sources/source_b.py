"""源B — 搜索并下载文档（压缩包格式，自动解压）。"""

import json
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.sources import BaseSource, register


@register("b")
class SourceB(BaseSource):
    title = "源B"
    description = "搜索并下载文档（自动解压）"

    def _base(self) -> str:
        return settings.source_b_url

    def search(self, keyword: str) -> list[dict[str, Any]]:
        if not settings.source_b_enabled or not settings.source_b_url:
            return []

        # 使用 Alist 搜索 API
        url = f"{self._base()}/api/fs/search"
        data = json.dumps({
            "parent": settings.source_b_path,
            "name": keyword,
            "page": 1,
            "per_page": 30,
        }).encode()
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.loads(resp.read().decode())
        except Exception:
            return []

        if d.get("code") != 200:
            return []

        results = []
        seen = set()
        for item in d.get("data", {}).get("content", []):
            name = item.get("name", "")
            if name not in seen:
                seen.add(name)
                size = item.get("size", 0)
                size_hint = f"{size / 1024 / 1024:.1f}MB" if size else ""
                results.append({
                    "id": name,
                    "title": name.replace(".rar", "").replace(".zip", ""),
                    "source": "b",
                    "size_hint": size_hint,
                    "file_name": name,
                })
        return results[:30]

    def get_download_url(self, book_id: str) -> str:
        encoded = urllib.parse.quote(book_id)
        return f"{self._base()}/{encoded}"

    def download_and_extract(self, book_id: str, target_dir: str) -> str | None:
        filename = book_id
        ext = os.path.splitext(filename)[1].lower()
        file_path = os.path.join(target_dir, filename)

        # 已下载则直接返回
        if os.path.exists(file_path):
            return file_path

        # 下载
        url = self.get_download_url(book_id)
        parsed = urllib.parse.urlparse(url)
        safe_url = f"{parsed.scheme}://{parsed.netloc}{urllib.parse.quote(parsed.path, safe='/:')}"
        try:
            req = urllib.request.Request(safe_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                os.makedirs(target_dir, exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(data)
        except Exception:
            return None

        if not os.path.exists(file_path):
            return None

        # 解压
        if ext == ".rar" and subprocess.run(["unrar", "e", "-o+", file_path, target_dir],
                                             capture_output=True, timeout=60).returncode == 0:
            os.remove(file_path)
            # 查找解压后的同名文件
            stem = filename.rsplit(".", 1)[0]
            for f in os.listdir(target_dir):
                if f.startswith(stem):
                    return os.path.join(target_dir, f)

        return file_path

    def get_detail(self, book_id: str) -> dict[str, Any]:
        return {"id": book_id, "title": book_id, "download_url": self.get_download_url(book_id)}
