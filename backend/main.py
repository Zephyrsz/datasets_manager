from contextlib import asynccontextmanager
import os
from pathlib import Path
import sqlite3
from typing import Annotated, Literal

from fastapi import FastAPI, Path as ApiPath, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from import_dataset import DEFAULT_DB
from .models import DatasetConfig, SubtitleUpdate
from .service import DatasetService


PositiveId = Annotated[int, ApiPath(gt=0, le=9223372036854775807)]


def create_app(database=None):
    service = DatasetService(database or os.environ.get("DATASETS_DB", DEFAULT_DB))
    origins = [value.strip() for value in os.environ.get(
        "FRONTEND_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
    ).split(",") if value.strip()]

    @asynccontextmanager
    async def lifespan(app):
        service.initialize()
        yield

    app = FastAPI(title="语音数据集管理 API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Range"], expose_headers=["Content-Range", "Accept-Ranges"],
    )

    @app.middleware("http")
    async def check_write_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and origin not in origins:
            return JSONResponse(status_code=403, content={"detail": "此来源无权修改本地数据"})
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid_value(request, error):
        return JSONResponse(status_code=400, content={"detail": f"数据校验失败：{error}"})

    @app.exception_handler(OSError)
    async def invalid_path(request, error):
        return JSONResponse(status_code=400, content={"detail": f"无法读取源文件，请检查目录或权限：{error}"})

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return JSONResponse(status_code=409, content={"detail": "数据库操作失败，请确认数据结构或稍后重试"})

    @app.get("/api/health")
    def health():
        with service.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": str(service.database)}

    @app.get("/api/datasets")
    def datasets():
        return service.list_datasets()

    @app.post("/api/datasets", status_code=201)
    def create_dataset(config: DatasetConfig):
        return service.create(config)

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: PositiveId):
        return service.get_dataset(dataset_id)

    @app.put("/api/datasets/{dataset_id}")
    def configure_dataset(dataset_id: PositiveId, config: DatasetConfig):
        return service.configure(dataset_id, config)

    @app.post("/api/datasets/{dataset_id}/sync")
    def sync_dataset(dataset_id: PositiveId):
        return service.sync(dataset_id)

    @app.get("/api/datasets/{dataset_id}/records")
    def records(
        dataset_id: PositiveId,
        page: Annotated[int, Query(ge=1, le=10000000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        q: Annotated[str, Query(max_length=500)] = "",
        subtitle: Literal["all", "present", "missing"] = "all",
    ):
        return service.list_records(dataset_id, page, page_size, q, subtitle)

    @app.patch("/api/datasets/{dataset_id}/records/{record_id}")
    def update_subtitle(dataset_id: PositiveId, record_id: PositiveId, value: SubtitleUpdate):
        return service.update_subtitle(dataset_id, record_id, value.subtitle)

    @app.get("/api/datasets/{dataset_id}/records/{record_id}/audio")
    def audio(dataset_id: PositiveId, record_id: PositiveId):
        return FileResponse(service.audio_file(dataset_id, record_id), media_type="audio/wav")

    return app


app = create_app()
