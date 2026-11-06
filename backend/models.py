from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DatasetConfig(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    storage_dir: str = Field(min_length=1, max_length=4096)
    audio_subdir: str = Field(default="wav", max_length=1024)
    transcript_path: str | None = Field(default=None, max_length=4096)

    @field_validator("name", "storage_dir", "audio_subdir")
    @classmethod
    def trim_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("transcript_path")
    @classmethod
    def normalize_optional(cls, value):
        return value.strip() or None if value is not None else None


class ResultRegistrationConfig(DatasetConfig):
    transcript_path: str = Field(default="transcript_utf8.txt", min_length=1, max_length=4096)

    @field_validator("transcript_path")
    @classmethod
    def require_transcript(cls, value):
        if not value:
            raise ValueError("结果登记必须提供字幕文件")
        return value


class SubtitleUpdate(BaseModel):
    subtitle: str | None = Field(max_length=20000)


class AudioConfig(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    file_path: str = Field(min_length=1, max_length=4096)
    kind: Literal["source", "reference"]
    speaker: str | None = Field(default=None, max_length=160)
    language: str | None = Field(default=None, max_length=80)
    reference_text: str | None = Field(default=None, max_length=20000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("name", "file_path")
    @classmethod
    def trim_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("名称和音频路径不能为空")
        return value

    @field_validator("speaker", "language", "reference_text", "notes")
    @classmethod
    def trim_optional(cls, value):
        return value.strip() or None if value is not None else None
