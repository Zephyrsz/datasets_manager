-- SQLite schema for datasets and single audio registrations; import_dataset.py creates audio_dataset_<id> dynamically.

CREATE TABLE audio_datasets (
    id              INTEGER PRIMARY KEY CHECK (id > 0),
    name            TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    storage_dir     TEXT NOT NULL UNIQUE CHECK (length(storage_dir) > 0),
    audio_subdir    TEXT NOT NULL DEFAULT 'wav',
    transcript_path TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE audio_dataset_1 (
    id         INTEGER PRIMARY KEY CHECK (id > 0),
    subtitle   TEXT,
    audio_name TEXT NOT NULL UNIQUE
        CHECK (length(trim(audio_name)) > 0
               AND audio_name NOT IN ('.', '..')
               AND instr(audio_name, '/') = 0
               AND instr(audio_name, char(92)) = 0)
);

-- Single-file registrations; created additively on API startup.
CREATE TABLE audio_assets (
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
);
CREATE INDEX audio_assets_kind_id ON audio_assets(kind, id);
