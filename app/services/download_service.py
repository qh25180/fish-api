"""Download service: fetch novel files from URLs with safety checks."""

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import httpx

from app.config import settings


async def _generate_unique_filename(
    directory: Path,
    original_name: str,
) -> tuple[Path, bool]:
    """Generate a unique filename to avoid overwriting existing files.

    If the file already exists, appends `` (1)``, `` (2)``, etc.
    Returns (final_path, was_renamed).
    """
    file_path = directory / original_name
    if not file_path.exists():
        return file_path, False

    stem = Path(original_name).stem
    suffix = Path(original_name).suffix

    counter = 1
    while True:
        new_name = f"{stem} ({counter}){suffix}"
        new_path = directory / new_name
        if not new_path.exists():
            return new_path, True
        counter += 1


def _check_url_allowed(url: str) -> None:
    """检查 URL 目标地址是否允许下载。

    阻止回环/链路本地地址；
    私有地址仅在 download_allow_intranet 开启时放行。
    """
    host = urlparse(url).hostname
    if not host:
        raise ValueError("无效的 URL")

    # 收集待检查的 IP 列表
    ips_to_check: list[str] = []

    # 如果 host 本身是 IP 字面量
    try:
        ips_to_check.append(ipaddress.ip_address(host).compressed)
    except ValueError:
        # host 是域名 → DNS 解析
        try:
            addrinfo = socket.getaddrinfo(host, 80)
            ips_to_check = list(set(
                addr[4][0] for addr in addrinfo
            ))
        except OSError:
            # DNS 解析失败，无法判断，安全起见阻止
            raise ValueError(f"无法解析域名: {host}")

    for ip_str in ips_to_check:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback or ip.is_link_local:
            raise ValueError("不允许下载回环或链路本地地址")
        if ip.is_private and not settings.download_allow_intranet:
            raise ValueError(
                "内网下载未开放（设置 DOWNLOAD_ALLOW_INTRANET=true 可开启）"
            )


def _extract_filename(url: str, content_disposition: str) -> str:
    """Extract filename from Content-Disposition header or URL."""
    from urllib.parse import urlparse, unquote

    if "filename=" in content_disposition:
        raw = content_disposition.split("filename=")[-1].strip('"\'')
        if raw:
            return unquote(raw)

    # Extract from URL path
    path = urlparse(url).path
    name = os.path.basename(path)
    if name:
        decoded = unquote(name)
        if decoded.strip():
            return decoded

    return "download.txt"


def _ensure_allowed_extension(filename: str) -> str:
    """Ensure the filename has an allowed text extension."""
    allowed_exts = settings.text_file_extensions_list
    ext = Path(filename).suffix.lower()

    if ext in allowed_exts:
        return filename

    # Append .txt as default
    return Path(filename).stem + ".txt"


async def download_novel(url: str) -> dict:
    """Download a novel file from a URL and save to the configured directory.

    Returns download result dict matching DownloadResponse schema.
    """
    max_size = settings.max_file_size_mb * 1024 * 1024
    timeout = settings.download_timeout_seconds

    novels_dir = settings.text_files_dir
    novels_dir.mkdir(parents=True, exist_ok=True)

    limits = httpx.Limits(
        max_keepalive_connections=5,
        max_connections=10,
    )

    # 请求前先校验 URL 安全性（此时尚未建立连接）
    _check_url_allowed(url)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        limits=limits,
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()

            # 重定向后再次校验最终 URL（防止 302 跳转到内网）
            _check_url_allowed(str(response.url))

            # Determine filename
            content_disposition = response.headers.get("content-disposition", "")
            raw_name = _extract_filename(url, content_disposition)
            raw_name = os.path.basename(raw_name)
            raw_name = _ensure_allowed_extension(raw_name)

            # Generate unique path
            save_path, renamed = await _generate_unique_filename(novels_dir, raw_name)

            # Stream download with size limit
            file_size = 0
            async with aiofiles.open(save_path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    file_size += len(chunk)
                    if file_size > max_size:
                        raise ValueError(
                            f"文件超过大小限制 {settings.max_file_size_mb}MB"
                        )
                    await f.write(chunk)

    return {
        "filename": save_path.name,
        "original_filename": raw_name,
        "save_path": str(save_path),
        "file_size": file_size,
        "renamed": renamed,
    }
