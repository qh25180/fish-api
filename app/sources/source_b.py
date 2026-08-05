"""源B — 搜索并下载文档（压缩包格式，自动解压）。"""

import json
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.sources import BaseSource, register
from app.utils.meta_util import extract_meta


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁止自动跟随重定向（防重定向链 SSRF：攻击者源返回 302 → 内网地址）。"""

    def redirect_request(self, *args, **kwargs):
        # 返回 None 表示不跟随，让 urlopen 抛 HTTPError（3xx）
        return None


@register("b")
class SourceB(BaseSource):
    title = "源B"
    description = "搜索并下载文档（自动解压）"

    def _base(self) -> str:
        return settings.source_b_url

    def search(self, keyword: str) -> list[dict[str, Any]]:
        if not settings.source_b_enabled or not settings.source_b_url:
            return []

        # 使用 Alist 搜索 API。
        # 注意：此后端对 POST /api/fs/search 返回 400（page can't < 1，body 未正确解析），
        # 因此改用 GET + query 参数调用（Alist 的 g.Any 路由支持 GET）。
        params = urllib.parse.urlencode({
            "parent": settings.source_b_path,
            "keywords": keyword,
            "scope": 2,  # 2 = 仅文件
            "page": 1,
            "per_page": 30,
        })
        url = f"{self._base()}/api/fs/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
            if item.get("is_dir"):
                continue
            if name not in seen:
                seen.add(name)
                size = item.get("size", 0)
                size_hint = f"{size / 1024 / 1024:.1f}MB" if size else ""
                meta = extract_meta(name)
                results.append({
                    "id": name,
                    "title": meta["title"],
                    "author": meta["author"],
                    "source": "b",
                    "size_hint": size_hint,
                    "file_name": name,
                })
        return results[:30]

    def get_download_url(self, book_id: str) -> str:
        encoded = urllib.parse.quote(book_id, safe='/:')
        return f"{self._base()}/{encoded}"

    def download_and_extract(self, book_id: str, target_dir: str) -> str | None:
        # 安全：book_id 仅取 basename + 扩展名白名单（防路径穿越/任意文件写）
        filename = os.path.basename(book_id)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".rar", ".zip", ".txt", ""):
            return None
        if not filename:
            return None
        # 目标目录必须是配置的小说目录（防穿越）
        target_dir = os.path.realpath(target_dir)
        file_path = os.path.realpath(os.path.join(target_dir, filename))
        if not file_path.startswith(target_dir + os.sep):
            return None

        # 已下载则直接返回
        if os.path.exists(file_path):
            return file_path

        # 下载（单次编码，防二次 % 编码破坏中文文件名）
        url = self.get_download_url(book_id)
        parsed = urllib.parse.urlparse(url)
        # 校验 hostname 与 scheme（防 SSRF/非 http 协议）
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        try:
            # 禁用系统代理 + 禁用自动重定向（防代理逃逸/重定向链 SSRF）
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                _NoRedirectHandler(),  # 移除自动重定向跟随
            )
            req = urllib.request.Request(safe_url, headers={"User-Agent": "Mozilla/5.0"})
            # 流式下载 + 大小限制（防 OOM/磁盘炸弹）
            max_size = settings.max_file_size_mb * 1024 * 1024
            os.makedirs(target_dir, exist_ok=True)
            with opener.open(req, timeout=120) as resp:
                # 不自动跟随重定向：3xx 直接拒绝（Alist 直链不应重定向）
                written = 0
                with open(file_path, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_size:
                            f.close()
                            os.remove(file_path)
                            return None
                        f.write(chunk)
        except Exception:
            return None

        if not os.path.exists(file_path):
            return None

        # 解压到独立临时子目录，防 zip-slip（恶意条目 ../ 写出目标目录）
        if ext in (".rar", ".zip"):
            import tempfile
            import shutil
            tmp_dir = tempfile.mkdtemp(prefix="qb_srcb_", dir=target_dir)
            try:
                if ext == ".rar":
                    ok = subprocess.run(
                        ["unrar", "e", "-o+", file_path, tmp_dir],
                        capture_output=True, timeout=60,
                    ).returncode == 0
                else:
                    ok = subprocess.run(
                        ["unzip", "-o", "-j", file_path, "-d", tmp_dir],
                        capture_output=True, timeout=60,
                    ).returncode == 0
                if ok:
                    # 解压结果大小限制（防压缩炸弹占满磁盘）
                    max_size = settings.max_file_size_mb * 1024 * 1024
                    total_extracted = sum(
                        os.path.getsize(os.path.join(tmp_dir, f))
                        for f in os.listdir(tmp_dir)
                        if os.path.isfile(os.path.join(tmp_dir, f))
                    )
                    if total_extracted > max_size:
                        return None
                    # 精确匹配解压出的同名 txt（非前缀模糊）
                    stem = filename.rsplit(".", 1)[0]
                    for f in os.listdir(tmp_dir):
                        # 校验解压文件在临时目录内
                        cand = os.path.realpath(os.path.join(tmp_dir, f))
                        if not cand.startswith(tmp_dir + os.sep):
                            continue
                        base = os.path.basename(cand)
                        if base == stem or base == stem + ".txt":
                            # 移动到目标目录（仅当目标不存在）
                            dest = os.path.join(target_dir, base)
                            if not os.path.exists(dest):
                                shutil.move(cand, dest)
                            return dest
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                if os.path.exists(file_path):
                    os.remove(file_path)
            return None

        return file_path

    def get_detail(self, book_id: str) -> dict[str, Any]:
        return {"id": book_id, "title": book_id, "download_url": self.get_download_url(book_id)}
