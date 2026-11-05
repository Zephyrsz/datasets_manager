-- SQLite schema exported from datasets.sqlite3; import_dataset.py creates audio_dataset_<id> dynamically.

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
