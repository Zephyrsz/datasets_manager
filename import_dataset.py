#!/usr/bin/env python3
"""Register a local WAV dataset and import an optional JSUT-format transcript."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


DEFAULT_DB = Path(__file__).resolve().parent / "datasets.sqlite3"


class RegistrationConflict(ValueError):
    """A registration would change an existing dataset's identity or file set."""


REGISTRY_SQL = """
CREATE TABLE IF NOT EXISTS audio_datasets (
    id              INTEGER PRIMARY KEY CHECK (id > 0),
    name            TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    storage_dir     TEXT NOT NULL UNIQUE CHECK (length(storage_dir) > 0),
    audio_subdir    TEXT NOT NULL DEFAULT 'wav',
    transcript_path TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

# Only the validated positive integer dataset ID is substituted into this SQL.
DETAIL_SQL = """
CREATE TABLE {table_name} (
    id         INTEGER PRIMARY KEY CHECK (id > 0),
    subtitle   TEXT,
    audio_name TEXT NOT NULL UNIQUE
        CHECK (length(trim(audio_name)) > 0
               AND audio_name NOT IN ('.', '..')
               AND instr(audio_name, '/') = 0
               AND instr(audio_name, char(92)) = 0)
)
"""


def read_source(root, audio_subdir, transcript):
    """Validate sources before opening the database; never modify source files."""
    root = Path(root).expanduser().resolve(strict=True)
    subdir = Path(audio_subdir)
    if not root.is_dir():
        raise ValueError("Dataset root must be a directory")
    if subdir.is_absolute() or ".." in subdir.parts or "\\" in audio_subdir:
        raise ValueError("audio_subdir must be a relative directory without '..'")
    audio_dir = (root / subdir).resolve(strict=True)
    if not audio_dir.is_relative_to(root) or not audio_dir.is_dir():
        raise ValueError("Audio directory must be inside the dataset root")
    audio_names = sorted(
        p.name for p in audio_dir.iterdir() if p.is_file() and p.suffix.lower() == ".wav"
    )
    if not audio_names:
        raise ValueError("No WAV files found in the audio directory")
    if any("\\" in name for name in audio_names):
        raise ValueError("Audio filenames must not contain backslashes")
    if len({Path(name).stem for name in audio_names}) != len(audio_names):
        raise ValueError("Multiple audio files share a transcript key")

    transcript_path = None
    subtitles = {}
    if transcript is not None:
        transcript_path = Path(transcript).expanduser()
        if not transcript_path.is_absolute():
            transcript_path = root / transcript_path
        transcript_path = transcript_path.resolve(strict=True)
        for line_number, line in enumerate(
            transcript_path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            if not line.strip():
                continue
            key, separator, subtitle = line.partition(":")
            key = key.strip()
            if not separator or not key or not subtitle.strip():
                raise ValueError(f"Invalid transcript at line {line_number}: expected key:text")
            if key in subtitles:
                raise ValueError(f"Duplicate transcript key at line {line_number}: {key}")
            subtitles[key] = subtitle
        audio_keys = {Path(name).stem for name in audio_names}
        missing = sorted(audio_keys - subtitles.keys())
        orphan = sorted(subtitles.keys() - audio_keys)
        if missing or orphan:
            raise ValueError(
                f"Audio/transcript mismatch: {len(missing)} missing subtitles, "
                f"{len(orphan)} transcripts without audio; "
                f"missing examples={missing[:3]}, orphan examples={orphan[:3]}"
            )

    records = [(name, subtitles.get(Path(name).stem)) for name in audio_names]
    return root, subdir.as_posix(), transcript_path, records


def import_dataset(*, db, name, root, audio_subdir="wav", transcript=None, dataset_id=None,
                   on_existing="update", validate_source=None):
    """Import one source snapshot, optionally validating it before any DB writes."""
    if on_existing not in {"update", "reuse"}:
        raise ValueError("on_existing must be 'update' or 'reuse'")
    if not name.strip():
        raise ValueError("Dataset name must not be empty")
    if dataset_id is not None and (
        type(dataset_id) is not int or not 0 < dataset_id <= 9223372036854775807
    ):
        raise ValueError("dataset_id must be a positive SQLite integer")
    root, audio_subdir, transcript_path, records = read_source(root, audio_subdir, transcript)
    if validate_source is not None:
        validate_source(root, audio_subdir, transcript_path, records)
    db = Path(db).expanduser().resolve()
    metadata = (name, str(root), audio_subdir, str(transcript_path) if transcript_path else None)

    with closing(sqlite3.connect(db, timeout=30)) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(REGISTRY_SQL)
            matches = conn.execute(
                "SELECT id, name, storage_dir, audio_subdir, transcript_path "
                "FROM audio_datasets WHERE name = ? OR storage_dir = ? OR id = ?",
                (name, str(root), dataset_id),
            ).fetchall()
            if matches:
                if len(matches) != 1 or tuple(matches[0][1:]) != metadata or (
                    dataset_id is not None and matches[0][0] != dataset_id
                ):
                    raise RegistrationConflict("Conflicting dataset registration; existing metadata was preserved")
                dataset_id = matches[0][0]
                is_new = False
            else:
                cursor = conn.execute(
                    "INSERT INTO audio_datasets "
                    "(id, name, storage_dir, audio_subdir, transcript_path) VALUES (?, ?, ?, ?, ?)",
                    (dataset_id, *metadata),
                )
                dataset_id = cursor.lastrowid
                is_new = True

            table_name = f"audio_dataset_{dataset_id}"
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = ?", (table_name,)
            ).fetchone() is not None
            if is_new:
                if table_exists:
                    raise ValueError(f"Unregistered detail table already exists: {table_name}")
                conn.execute(DETAIL_SQL.format(table_name=table_name))
            elif not table_exists:
                raise ValueError(f"Registered detail table is missing: {table_name}")

            existing = dict(conn.execute(f"SELECT audio_name, subtitle FROM {table_name}"))
            reuse = not is_new and on_existing == "reuse"
            if reuse and existing.keys() != {name for name, _ in records}:
                raise RegistrationConflict(
                    "Registered audio file set changed; use a new dataset name and directory"
                )
            removed = sorted(existing.keys() - {name for name, _ in records})
            if removed:
                raise ValueError(
                    f"{len(removed)} registered audio files are missing from the source; "
                    f"no records were deleted: {removed[:3]}"
                )
            inserted = updated = 0
            if not reuse:
                inserted = sum(audio_name not in existing for audio_name, _ in records)
                updated = sum(
                    audio_name in existing and existing[audio_name] != subtitle
                    for audio_name, subtitle in records
                )
                conn.executemany(
                    f"INSERT INTO {table_name} (audio_name, subtitle) VALUES (?, ?) "
                    "ON CONFLICT(audio_name) DO UPDATE SET subtitle = excluded.subtitle "
                    "WHERE subtitle IS NOT excluded.subtitle",
                    records,
                )
            total = conn.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
            null_subtitles = conn.execute(
                f"SELECT count(*) FROM {table_name} WHERE subtitle IS NULL"
            ).fetchone()[0]

    result = {
        "database": str(db),
        "dataset_id": dataset_id,
        "detail_table": table_name,
        "total_records": total,
        "inserted_records": inserted,
        "updated_records": updated,
        "unchanged_records": total - inserted - updated,
        "null_subtitles": null_subtitles,
    }
    if on_existing == "reuse":
        result["registration_status"] = "created" if is_new else "existing"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--name", required=True, help="Unique registered dataset name")
    parser.add_argument("--root", type=Path, required=True, help="Dataset storage directory")
    parser.add_argument("--audio-subdir", default="wav", help="Audio directory relative to root")
    parser.add_argument("--transcript", help="Optional UTF-8 key:text file; relative to root or absolute")
    parser.add_argument("--dataset-id", type=int, help="Positive ID; allocated automatically when omitted")
    args = parser.parse_args()
    try:
        result = import_dataset(**vars(args))
    except (OSError, UnicodeError, ValueError, sqlite3.Error) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
