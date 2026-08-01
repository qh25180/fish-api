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
