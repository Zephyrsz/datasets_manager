from contextlib import contextmanager
from pathlib import Path
import sqlite3
import wave

from fastapi import HTTPException

from import_dataset import REGISTRY_SQL, RegistrationConflict, import_dataset, read_source
from register_result import register_result
from .models import DatasetConfig


class DatasetService:
    def __init__(self, database):
        self.database = Path(database).expanduser().resolve()

    @contextmanager
    def connect(self, *, write=False):
        conn = sqlite3.connect(self.database, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except Exception:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.connect(write=True) as conn:
            conn.execute(REGISTRY_SQL)

    @staticmethod
    def table_name(dataset_id):
        if type(dataset_id) is not int or not 0 < dataset_id <= 9223372036854775807:
            raise HTTPException(422, "数据集 ID 必须为正整数")
        return f"audio_dataset_{dataset_id}"

    def registration(self, conn, dataset_id):
        table = self.table_name(dataset_id)
        row = conn.execute("SELECT * FROM audio_datasets WHERE id = ?", (dataset_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "数据集不存在，请刷新列表")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
            raise HTTPException(409, "该数据集的明细表不存在，请检查数据库")
        return dict(row)

    def describe(self, conn, row):
        table = self.table_name(row["id"])
        counts = conn.execute(
            f"SELECT count(*) AS total, count(CASE WHEN subtitle IS NOT NULL AND trim(subtitle) <> '' THEN 1 END) AS subtitles FROM {table}"
        ).fetchone()
        return {
            **row, "detail_table": table, "record_count": counts["total"],
            "subtitle_count": counts["subtitles"],
            "storage_available": Path(row["storage_dir"]).is_dir(),
        }

    def list_datasets(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM audio_datasets ORDER BY created_at DESC, id DESC").fetchall()
            return {"items": [self.describe(conn, self.registration(conn, row["id"])) for row in rows]}

    def get_dataset(self, dataset_id):
        with self.connect() as conn:
            return self.describe(conn, self.registration(conn, dataset_id))

    @staticmethod
    def source(config):
        root = Path(config.storage_dir).expanduser()
        if not root.is_absolute():
            raise HTTPException(400, "数据集根目录必须是后端服务器上的绝对路径")
        return read_source(root, config.audio_subdir, config.transcript_path)

    def create(self, config):
        root, subdir, transcript, _ = self.source(config)
        with self.connect() as conn:
            if conn.execute("SELECT id FROM audio_datasets WHERE name=? OR storage_dir=?", (config.name, str(root))).fetchone():
                raise HTTPException(409, "该名称或目录已注册，请在已有数据集中编辑配置")
        result = import_dataset(
            db=self.database, name=config.name, root=root,
            audio_subdir=subdir, transcript=transcript,
        )
        return self.get_dataset(result["dataset_id"])

    def register_result(self, config):
        root = Path(config.storage_dir).expanduser()
        if not root.is_absolute():
            raise HTTPException(400, "数据集根目录必须是后端服务器上的绝对路径")
        try:
            result = register_result(
                db=self.database, name=config.name, root=root,
                audio_subdir=config.audio_subdir, transcript=config.transcript_path,
            )
        except RegistrationConflict as error:
            raise HTTPException(409, str(error)) from error
        return {
            "status": result["registration_status"],
            "dataset": self.get_dataset(result["dataset_id"]),
            "import_result": result,
        }

    def configure(self, dataset_id, config):
        current = self.get_dataset(dataset_id)
        new_root = Path(config.storage_dir).expanduser()
        old_root = Path(current["storage_dir"])
        if (new_root.is_absolute() and new_root.resolve() != old_root
                and config.transcript_path
                and config.transcript_path == current["transcript_path"]):
            # Stored paths are absolute. Keep a dataset-local transcript attached to
            # its root when only that root changes, even if the old directory is gone.
            try:
                relative_transcript = Path(config.transcript_path).relative_to(old_root)
            except ValueError:
                pass  # An explicitly external transcript stays at its own location.
            else:
                config = config.model_copy(update={
                    "transcript_path": str(new_root / relative_transcript),
                })
        root, subdir, transcript, records = self.source(config)
        table = self.table_name(dataset_id)
        with self.connect(write=True) as conn:
            self.registration(conn, dataset_id)
            source_names = {name for name, _ in records}
            existing_names = {row[0] for row in conn.execute(f"SELECT audio_name FROM {table}")}
            if not existing_names.issubset(source_names):
                raise HTTPException(400, "新目录缺少已登记的音频，配置未保存")
            try:
                conn.execute(
                    "UPDATE audio_datasets SET name=?, storage_dir=?, audio_subdir=?, transcript_path=? WHERE id=?",
                    (config.name, str(root), subdir, str(transcript) if transcript else None, dataset_id),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "数据集名称或目录已被其他数据集使用") from exc
        return self.get_dataset(dataset_id)

    def sync(self, dataset_id):
        row = self.get_dataset(dataset_id)
        return import_dataset(
            db=self.database, dataset_id=dataset_id, name=row["name"], root=row["storage_dir"],
            audio_subdir=row["audio_subdir"], transcript=row["transcript_path"],
        )

    @staticmethod
    def safe_audio_path(dataset, audio_name):
        if not audio_name or Path(audio_name).name != audio_name or "\\" in audio_name or audio_name in (".", ".."):
            raise HTTPException(400, "音频文件名不合法")
        root = Path(dataset["storage_dir"]).resolve()
        directory = (root / dataset["audio_subdir"]).resolve()
        audio = (directory / audio_name).resolve()
        if not directory.is_relative_to(root) or not audio.is_relative_to(directory):
            raise HTTPException(400, "音频路径超出数据集目录")
        if not audio.is_file():
            raise HTTPException(404, "音频文件不存在，请检查存储配置")
        return audio

    def record_info(self, dataset, row):
        record = dict(row)
        record.update(audio_available=False, size_bytes=None, duration_seconds=None)
        try:
            audio = self.safe_audio_path(dataset, record["audio_name"])
            record.update(audio_available=True, size_bytes=audio.stat().st_size)
            try:
                with wave.open(str(audio), "rb") as wav:
                    record["duration_seconds"] = round(wav.getnframes() / wav.getframerate(), 3)
            except (wave.Error, EOFError, ZeroDivisionError):
                pass
        except (HTTPException, OSError):
            pass
        return record

    def list_records(self, dataset_id, page, page_size, q, subtitle):
        table = self.table_name(dataset_id)
        clauses, values = [], []
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(audio_name LIKE ? ESCAPE '\\' OR subtitle LIKE ? ESCAPE '\\')")
            values += [f"%{escaped}%", f"%{escaped}%"]
        if subtitle == "missing":
            clauses.append("(subtitle IS NULL OR trim(subtitle) = '')")
        elif subtitle == "present":
            clauses.append("(subtitle IS NOT NULL AND trim(subtitle) <> '')")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as conn:
            dataset = self.registration(conn, dataset_id)
            total = conn.execute(f"SELECT count(*) FROM {table}{where}", values).fetchone()[0]
            rows = conn.execute(
                f"SELECT id, audio_name, subtitle FROM {table}{where} ORDER BY id LIMIT ? OFFSET ?",
                (*values, page_size, (page - 1) * page_size),
            ).fetchall()
            return {
                "items": [self.record_info(dataset, row) for row in rows],
                "total": total, "page": page, "page_size": page_size,
            }

    def update_subtitle(self, dataset_id, record_id, subtitle):
        table = self.table_name(dataset_id)
        subtitle = subtitle if subtitle is not None and subtitle.strip() else None
        with self.connect(write=True) as conn:
            dataset = self.registration(conn, dataset_id)
            cursor = conn.execute(f"UPDATE {table} SET subtitle=? WHERE id=?", (subtitle, record_id))
            if not cursor.rowcount:
                raise HTTPException(404, "音频记录不存在，请刷新明细")
            row = conn.execute(f"SELECT id, audio_name, subtitle FROM {table} WHERE id=?", (record_id,)).fetchone()
            return self.record_info(dataset, row)

    def audio_file(self, dataset_id, record_id):
        table = self.table_name(dataset_id)
        with self.connect() as conn:
            dataset = self.registration(conn, dataset_id)
            row = conn.execute(f"SELECT audio_name FROM {table} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "音频记录不存在")
            return self.safe_audio_path(dataset, row[0])
