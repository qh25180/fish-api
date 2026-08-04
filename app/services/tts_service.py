"""TTS 合成服务层：Edge-TTS（微软）与局域网 Piper 统一封装。"""

import asyncio
import io
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Edge-TTS 语音缓存（避免每次实例化）
_EDGE_COMMUNICATE = None


async def synthesize_edge(text: str, voice: str = "") -> bytes:
    """调用微软 Edge-TTS 合成 mp3，返回音频字节。

    Args:
        text: 待合成文本
        voice: 语音名（如 zh-CN-XiaoxiaoNeural），空则用配置默认

    Returns:
        mp3 音频字节
    """
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts 未安装，Edge 引擎不可用")

    voice = voice or settings.tts_edge_voice
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    timeout = settings.tts_timeout_seconds
    # edge-tts 7.x：stream() 返回 async_generator（可直接 async for）
    # 用 asyncio.timeout 包裹实现超时（wait_for 不能直接作用于 async generator）
    async with asyncio.timeout(timeout):
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
    data = buf.getvalue()
    if not data:
        raise RuntimeError("Edge-TTS 合成结果为空")
    return data


async def synthesize_local(text: str) -> bytes:
    """调用局域网 Piper 容器合成 wav，返回音频字节。

    Args:
        text: 待合成文本

    Returns:
        wav 音频字节
    """
    url = settings.tts_local_url.rstrip("/") + "/tts"
    timeout = settings.tts_timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json={"text": text},
                headers={"Content-Type": "application/json"},
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Piper 服务返回错误: HTTP {e.response.status_code}") from e
    except httpx.ConnectError as e:
        raise RuntimeError(f"无法连接 Piper 服务（{url}）: {e}") from e
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Piper 合成超时: {e}") from e
    data = resp.content
    if not data:
        raise RuntimeError("Piper 合成结果为空")
    return data
