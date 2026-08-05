"""Download service: fetch novel files from URLs with safety checks."""

import asyncio
import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import aiofiles

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


def _check_hostname_allowed(hostname: str | None) -> None:
    """校验主机名：仅允许解析后的 IP 通过检查，拒绝域名直接连接（防 DNS 重绑定）。"""
    if not hostname:
        raise ValueError("无效的 URL")
    # 解析主机名并逐个校验（域名可能解析出多个 IP）
    try:
        addrinfo = socket.getaddrinfo(hostname, 80)
        for addr in addrinfo:
            ip = ipaddress.ip_address(addr[4][0])
            if ip.is_loopback or ip.is_link_local or ip.is_unspecified \
                    or ip.is_reserved or ip.is_multicast:
                raise ValueError("不允许下载回环、链路本地或保留地址")
            if ip.is_private and not settings.remote_download_allow_intranet:
                raise ValueError(
                    "内网下载未开放（设置 REMOTE_DOWNLOAD_ALLOW_INTRANET=true 可开启）"
                )
    except OSError:
        raise ValueError(f"无法解析域名: {hostname}")


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
    安全：解析后固定 IP 连接（防 DNS 重绑定），SNI/证书校验用原始域名，
    重定向逐跳校验（防重定向链绕过），禁系统代理（防代理逃逸）。
    """
    max_size = settings.max_file_size_mb * 1024 * 1024
    timeout = settings.download_timeout_seconds

    novels_dir = settings.text_files_dir
    novels_dir.mkdir(parents=True, exist_ok=True)

    # 解析并校验目标 IP（此时未建立连接）
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("无效的 URL")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("不支持的下载协议")
    _check_hostname_allowed(parsed.hostname)
    # 解析域名得 IP（解析失败阻止）
    try:
        resolved_ip = socket.gethostbyname(parsed.hostname)
    except OSError:
        raise ValueError(f"无法解析域名: {parsed.hostname}")
    # 校验解析出的 IP 本身（防多 A 记录中混入内网）
    rip = ipaddress.ip_address(resolved_ip)
    if rip.is_loopback or rip.is_link_local or rip.is_unspecified \
            or rip.is_reserved or rip.is_multicast:
        raise ValueError("不允许下载回环、链路本地或保留地址")
    if rip.is_private and not settings.remote_download_allow_intranet:
        raise ValueError(
            "内网下载未开放（设置 REMOTE_DOWNLOAD_ALLOW_INTRANET=true 可开启）"
        )

    current_url = url
    redirects = 0
    save_path = None
    try:
        while True:
            # 逐跳请求（同步 http.client，线程中执行；连接固定到已校验 IP）
            result = await asyncio.to_thread(
                _request_once, current_url, resolved_ip,
                timeout=timeout, max_size=max_size,
            )
            status = result["status"]
            headers = result["headers"]
            body = result["body"]  # 最终非重定向响应体（bytes）

            # 重定向：逐跳校验新目标后再跟随（最多 5 跳）
            if status in (301, 302, 303, 307, 308):
                if redirects >= 5:
                    raise ValueError("重定向次数过多")
                redirects += 1
                location = headers.get("location")
                if not location:
                    raise ValueError("重定向缺少 Location")
                from urllib.parse import urljoin
                next_url = urljoin(current_url, location)
                nxt_parsed = urlparse(next_url)
                if nxt_parsed.scheme not in ("http", "https"):
                    raise ValueError("不支持的下载协议")
                _check_hostname_allowed(nxt_parsed.hostname)
                # 新域名重新解析 + 校验 IP
                try:
                    resolved_ip = socket.gethostbyname(nxt_parsed.hostname)
                except OSError:
                    raise ValueError(f"无法解析域名: {nxt_parsed.hostname}")
                nrip = ipaddress.ip_address(resolved_ip)
                if nrip.is_loopback or nrip.is_link_local or nrip.is_unspecified \
                        or nrip.is_reserved or nrip.is_multicast:
                    raise ValueError("不允许下载回环、链路本地或保留地址")
                if nrip.is_private and not settings.remote_download_allow_intranet:
                    raise ValueError(
                        "内网下载未开放（设置 REMOTE_DOWNLOAD_ALLOW_INTRANET=true 可开启）"
                    )
                current_url = next_url
                continue

            if status >= 400:
                raise ValueError(f"下载失败: HTTP {status}")

            # Determine filename
            content_disposition = headers.get("content-disposition", "")
            raw_name = _extract_filename(url, content_disposition)
            raw_name = os.path.basename(raw_name)
            raw_name = _ensure_allowed_extension(raw_name)

            # Generate unique path
            save_path, renamed = await _generate_unique_filename(novels_dir, raw_name)

            # 写入（大小已在 _request_once 内限制）
            async with aiofiles.open(save_path, "wb") as f:
                await f.write(body)
            file_size = len(body)
            break
    except Exception:
        # 超限/异常时清理已写入的部分文件，防残留占盘
        if save_path is not None:
            try:
                save_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    return {
        "filename": save_path.name,
        "original_filename": raw_name,
        "file_size": file_size,
        "renamed": renamed,
    }


def _request_once(url: str, resolved_ip: str, timeout: int, max_size: int) -> dict:
    """同步执行单次 HTTP 请求：固定 IP 连接 + SNI 用域名（防 DNS 重绑定）。

    返回 {status, headers, body}；超限抛 ValueError。
    """
    import http.client
    import ssl

    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    # 固定 IP 建连（无 DNS 重解析）+ SNI/证书校验用原始域名
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    try:
        if parsed.scheme == "https":
            ctx = ssl.create_default_context()
            conn = conn_cls(
                host=parsed.hostname,  # SNI 用域名
                port=port,
                timeout=timeout,
                context=ctx,
                # 关键：绕过常规 host 解析，指定固定 IP
            )
            # 直接替换 socket：连接固定 IP，TLS 握手仍用域名做 SNI/校验
            raw_sock = socket.create_connection((resolved_ip, port), timeout=timeout)
            tls_sock = ctx.wrap_socket(raw_sock, server_hostname=parsed.hostname)
            conn.sock = tls_sock
        else:
            conn = conn_cls(host=parsed.hostname, port=port, timeout=timeout)
            raw_sock = socket.create_connection((resolved_ip, port), timeout=timeout)
            conn.sock = raw_sock

        conn.request("GET", path, headers={
            "User-Agent": "Mozilla/5.0",
            "Host": parsed.netloc,
            "Accept": "*/*",
        })
        resp = conn.getresponse()
        status = resp.status
        headers = {k.lower(): v for k, v in resp.getheaders()}
        # 流式读取 + 大小限制
        body = b""
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            body += chunk
            if len(body) > max_size:
                conn.close()
                raise ValueError(f"文件超过大小限制 {max_size // (1024*1024)}MB")
        conn.close()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"下载失败: {e}")

    return {"status": status, "headers": headers, "body": body}
