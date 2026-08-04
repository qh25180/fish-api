"""TTS 合成 API 路由（阅读页朗读用）。"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.security import request_token_ok
from app.services import tts_service

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])


class TTSRequest(BaseModel):
    engine: str = "edge"  # "edge" | "local"
    text: str = ""
    voice: str = ""


def _require_token(request: Request) -> None:
    """统一认证：Bearer / Cookie。API_TOKEN 配置时强制。"""
    if settings.api_token and (request is None or not request_token_ok(request)):
        raise HTTPException(status_code=403, detail="无效的访问口令")


@router.post("", summary="TTS 文本合成")
async def tts_synthesize(
    body: TTSRequest,
    request: Request = None,
):
    """合成指定文本为语音（edge=mp3，local=wav）。"""
    _require_token(request)

    engine = (body.engine or "edge").lower()
    text = (body.text or "").strip()

    # 引擎开关检查
    if engine == "edge":
        if not settings.tts_edge_enabled:
            raise HTTPException(status_code=403, detail="Edge 引擎未开放")
    elif engine == "local":
        if not settings.tts_local_enabled:
            raise HTTPException(status_code=403, detail="局域网 TTS 未开放")
    else:
        raise HTTPException(status_code=400, detail="engine 仅支持 edge 或 local")

    # 文本校验
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    if len(text) > settings.tts_max_text_length:
        raise HTTPException(
            status_code=400,
            detail=f"text 过长（{len(text)} 字，上限 {settings.tts_max_text_length}）",
        )

    # 合成
    try:
        if engine == "edge":
            data = await tts_service.synthesize_edge(text, body.voice)
            media_type = "audio/mpeg"
        else:
            data = await tts_service.synthesize_local(text)
            media_type = "audio/wav"
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:  # 兜底
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {e}")

    return Response(content=data, media_type=media_type)
