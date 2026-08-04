from pydantic_settings import BaseSettings
from pathlib import Path
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    text_files_dir: Path = Path("./novels")
    text_file_extensions: str = ".txt,.md"
    default_encoding: str = "auto"
    max_file_size_mb: int = 50
    download_timeout_seconds: int = 30
    upload_timeout_seconds: int = 300
    api_token: str = "qhapi-token"
    remote_download_enabled: bool = False
    remote_download_allow_intranet: bool = False
    upload_enabled: bool = False
    upload_chunk_size_kb: int = 512
    file_download_enabled: bool = False
    file_rename_pinyin: bool = False
    # 重命名模式（0=不重命名，1=小说名拼音，2=中文小说名，3=中文小说名-中文作者）。
    # 若未设置该变量（默认0）但 FILE_RENAME_PINYIN=true，则按模式1（拼音）处理，保持向后兼容。
    file_rename_mode: int = 0
    # Legado HTTP API 整体开关（默认开启，保持外部工具兼容）。
    # 注意：Legado 接口为外部协议，永不验证 token；关闭后相关接口返回 403 未开放。
    legado_enabled: bool = True
    # Swagger 文档开关（默认关闭；开启后 /docs、/openapi.json 需认证访问）。
    docs_enabled: bool = False
    source_a_enabled: bool = False
    source_a_url: str = ""
    source_a_name: str = "示例源A"
    source_b_enabled: bool = False
    source_b_url: str = ""
    source_b_path: str = "/"
    source_b_name: str = "示例源B"

    # ── TTS 朗读配置 ────────────────────────────────────────────
    # 阅读页朗读总开关（false 则前端隐藏朗读按钮）
    tts_enabled: bool = True
    # Edge-TTS 引擎开关（需要服务器能访问微软接口）
    tts_edge_enabled: bool = True
    # 局域网 Piper 引擎开关（需要自建 piper-tts 容器）
    tts_local_enabled: bool = True
    # 局域网 Piper 服务地址：fish-api 容器内经宿主机网关访问（宿主映射端口 5051）
    # 若 fish-api 与 piper 在同一 docker 网络，可改为 http://piper-tts:5001
    tts_local_url: str = "http://172.19.0.1:5051"
    # Edge-TTS 默认语音（晓晓，女声，中文自然）
    tts_edge_voice: str = "zh-CN-XiaoxiaoNeural"
    # 单次合成最大文本长度（超限 400 拒绝）
    tts_max_text_length: int = 8000
    # 合成超时（秒）
    tts_timeout_seconds: int = 120

    @property
    def text_file_extensions_list(self) -> List[str]:
        """Get allowed extensions as a list."""
        return [ext.strip().lower() for ext in self.text_file_extensions.split(",")]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
