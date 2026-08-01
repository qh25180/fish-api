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
    # 是否启用文本阅读页面（/read）及其操作的 token 验证。
    # 启用时（且配置了 API_TOKEN），访问 /read 及阅读器调用的
    # getBookshelf/getChapterList/getBookContent/saveBookProgress 等接口需携带 token。
    reader_token_enabled: bool = False
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
