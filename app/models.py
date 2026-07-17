"""Pydantic models for request/response schemas."""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ─── Novel List ───────────────────────────────────────────────

class NovelInfo(BaseModel):
    """Information about a single novel file."""
    filename: str
    file_size: int
    modified_time: datetime
    estimated_chapters: int


class NovelListResponse(BaseModel):
    """Response for listing novel files."""
    total: int
    page: int
    page_size: int
    novels: list[NovelInfo]


# ─── Chapters ─────────────────────────────────────────────────

class ChapterInfo(BaseModel):
    """Information about a single chapter."""
    chapter_number: int
    title: str
    start_pos: int


class ChapterListResponse(BaseModel):
    """Response for chapter list."""
    filename: str
    total_chapters: int
    chapters: list[ChapterInfo]


# ─── Content ──────────────────────────────────────────────────

class ContentResponse(BaseModel):
    """Response for text content retrieval."""
    filename: str
    start: int
    offset: int
    total_length: int
    content: str
    chapter_title: Optional[str] = None


# ─── Download ─────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    """Request to download a file from URL."""
    url: str
    token: str | None = None


class DownloadResponse(BaseModel):
    """Response for download operation."""
    filename: str
    original_filename: str
    save_path: str
    file_size: int
    renamed: bool
