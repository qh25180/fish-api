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
