"""Single audio registrations, independent from directory-based datasets."""

import json
import math
from pathlib import Path
import sqlite3
import subprocess

from fastapi import HTTPException


AUDIO_ASSETS_SQL = """
CREATE TABLE IF NOT EXISTS audio_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    file_path TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('source', 'reference')),
    speaker TEXT,
    language TEXT,
    reference_text TEXT,
    notes TEXT,
    duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    sample_rate INTEGER NOT NULL CHECK (sample_rate > 0),
    channels INTEGER NOT NULL CHECK (channels > 0),
    codec TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

AUDIO_TYPES = {
    '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.mp3': 'audio/mpeg',
    '.flac': 'audio/flac', '.ogg': 'audio/ogg', '.opus': 'audio/ogg',
    '.aac': 'audio/aac', '.webm': 'audio/webm',
    '.aif': 'audio/aiff', '.aiff': 'audio/aiff',
}


def probe_audio(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('请填写后端服务器上的音频绝对路径')
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in AUDIO_TYPES:
        raise ValueError('请选择 WAV、M4A、MP3、FLAC、OGG、OPUS、AAC、WebM 或 AIFF 音频文件')
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
            '-select_streams', 'a:0', '-show_entries',
            'stream=codec_name,sample_rate,channels,duration:format=duration',
            '-of', 'json', str(path),
        ], capture_output=True, text=True, timeout=20, check=False)
    except FileNotFoundError as error:
        raise HTTPException(503, '无法检查音频，请先在后端安装 FFmpeg（包含 ffprobe）') from error
    except subprocess.TimeoutExpired as error:
        raise ValueError('音频信息读取超时，请检查文件是否完整后重试') from error
    try:
        if result.returncode:
            raise ValueError('probe failed')
        data = json.loads(result.stdout)
        stream = data['streams'][0]
        duration = float(stream.get('duration') or data['format']['duration'])
        rate, channels = int(stream['sample_rate']), int(stream['channels'])
        codec = stream['codec_name']
        if not math.isfinite(duration) or duration <= 0 or rate <= 0 or channels <= 0 or not codec:
            raise ValueError('invalid metadata')
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ValueError('未检测到有效音轨或时长，请检查音频文件是否完整') from error
    return dict(file_path=str(path), duration_seconds=duration, size_bytes=path.stat().st_size,
                sample_rate=rate, channels=channels, codec=codec)


class AudioService:
    def __init__(self, storage):
        self.storage = storage

    def initialize(self):
        with self.storage.connect(write=True) as conn:
            conn.execute(AUDIO_ASSETS_SQL)
            conn.execute('CREATE INDEX IF NOT EXISTS audio_assets_kind_id ON audio_assets(kind, id)')

    @staticmethod
    def row(conn, audio_id):
        row = conn.execute('SELECT * FROM audio_assets WHERE id=?', (audio_id,)).fetchone()
        if row is None:
            raise HTTPException(404, '音频登记不存在，请刷新列表')
        return dict(row)

    @staticmethod
    def file_path(row):
        original = Path(row['file_path'])
        try:
            path = original.resolve(strict=True)
        except FileNotFoundError as error:
            raise HTTPException(404, '音频文件不存在，请编辑登记修复路径') from error
        if path != original:
            raise HTTPException(409, '音频路径已变更，请重新编辑登记确认文件')
        if not path.is_file():
            raise HTTPException(404, '音频文件不可用，请检查路径')
        return path

    @classmethod
    def describe(cls, row):
        try:
            cls.file_path(row)
            available = True
        except (HTTPException, OSError, ValueError, RuntimeError):
            available = False
        return {**row, 'file_available': available}

    def get(self, audio_id):
        with self.storage.connect() as conn:
            return self.describe(self.row(conn, audio_id))

    def list(self, page, page_size, q, kind):
        clauses, values = [], []
        if kind != 'all':
            clauses.append('kind=?')
            values.append(kind)
        if q:
            pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            clauses.append("(name LIKE ? ESCAPE '\\' OR file_path LIKE ? ESCAPE '\\' OR speaker LIKE ? ESCAPE '\\' OR reference_text LIKE ? ESCAPE '\\')")
            values.extend([pattern] * 4)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.storage.connect() as conn:
            total = conn.execute(f'SELECT count(*) FROM audio_assets{where}', values).fetchone()[0]
            rows = conn.execute(f'SELECT * FROM audio_assets{where} ORDER BY id DESC LIMIT ? OFFSET ?',
                                (*values, page_size, (page - 1) * page_size)).fetchall()
        return dict(items=[self.describe(dict(row)) for row in rows], total=total, page=page, page_size=page_size)

    def save(self, config, audio_id=None):
        if audio_id is not None:
            self.get(audio_id)
        metadata = probe_audio(config.file_path)
        values = {**config.model_dump(), **metadata}
        with self.storage.connect(write=True) as conn:
            if audio_id is not None:
                self.row(conn, audio_id)
            try:
                if audio_id is None:
                    columns = ', '.join(values)
                    placeholders = ', '.join('?' for _ in values)
                    audio_id = conn.execute(f'INSERT INTO audio_assets ({columns}) VALUES ({placeholders})', tuple(values.values())).lastrowid
                else:
                    assignments = ', '.join(f'{key}=?' for key in values)
                    conn.execute(f"UPDATE audio_assets SET {assignments}, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=?", (*values.values(), audio_id))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, '该音频路径已注册，请在已有登记中编辑用途或配置') from error
            row = self.row(conn, audio_id)
        return self.describe(row)

    def remove(self, audio_id):
        with self.storage.connect(write=True) as conn:
            self.row(conn, audio_id)
            conn.execute('DELETE FROM audio_assets WHERE id=?', (audio_id,))
        return {'status': 'removed', 'id': audio_id}

    def audio_file(self, audio_id):
        with self.storage.connect() as conn:
            row = self.row(conn, audio_id)
        path = self.file_path(row)
        return path, AUDIO_TYPES.get(path.suffix.lower(), 'application/octet-stream')
