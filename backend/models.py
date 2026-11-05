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


class SubtitleUpdate(BaseModel):
    subtitle: str | None = Field(max_length=20000)
