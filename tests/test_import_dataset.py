import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "import_dataset.py"


class ImportDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS aliases /var to /private/var; use the same canonical source path.
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "basic5000"
        (self.root / "wav").mkdir(parents=True)
        for name in ("BASIC5000_0001.wav", "BASIC5000_0002.wav"):
            (self.root / "wav" / name).write_bytes(b"audio fixture")
        self.transcript = self.root / "transcript_utf8.txt"
        self.transcript.write_text(
            "BASIC5000_0001:水を買います。\nBASIC5000_0002:時刻は12:30です。\n",
            encoding="utf-8",
        )
        self.db = self.base / "datasets.sqlite3"

    def run_import(self, *, with_transcript=True, dataset_id="1", name="basic5000"):
        args = [
            sys.executable, str(SCRIPT), "--db", str(self.db),
            "--name", name, "--root", str(self.root),
        ]
        if dataset_id is not None:
            args += ["--dataset-id", dataset_id]
        if with_transcript:
            args += ["--transcript", "transcript_utf8.txt"]
        return subprocess.run(args, text=True, capture_output=True)

    def rows(self, sql):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(sql).fetchall()

    def test_imports_registered_dataset_and_matching_japanese_subtitles(self):
        result = self.run_import()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows("SELECT id, name, storage_dir, audio_subdir, transcript_path FROM audio_datasets"), [
            (1, "basic5000", str(self.root), "wav", str(self.transcript))
        ])
        self.assertEqual(self.rows("SELECT id, audio_name, subtitle FROM audio_dataset_1 ORDER BY id"), [
            (1, "BASIC5000_0001.wav", "水を買います。"),
            (2, "BASIC5000_0002.wav", "時刻は12:30です。"),
        ])
        self.assertEqual(json.loads(result.stdout)["total_records"], 2)

    def test_reimport_keeps_ids_and_updates_subtitles_without_duplicates(self):
        first = self.run_import()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.transcript.write_text(
            "BASIC5000_0001:修正した字幕。\nBASIC5000_0002:時刻は12:30です。\n",
            encoding="utf-8",
        )
        result = self.run_import(dataset_id=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows("SELECT id, audio_name FROM audio_dataset_1 ORDER BY id"), [
            (1, "BASIC5000_0001.wav"), (2, "BASIC5000_0002.wav")
        ])
        self.assertEqual(self.rows("SELECT subtitle FROM audio_dataset_1 WHERE id=1"), [("修正した字幕。",)])
        self.assertEqual(self.rows("SELECT count(*) FROM audio_datasets"), [(1,)])
        self.assertEqual(json.loads(result.stdout)["updated_records"], 1)

    def test_no_transcript_stores_null_paths_and_subtitles(self):
        result = self.run_import(with_transcript=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows("SELECT transcript_path FROM audio_datasets"), [(None,)])
        self.assertEqual(self.rows("SELECT subtitle FROM audio_dataset_1"), [(None,), (None,)])

    def test_missing_or_orphan_subtitles_do_not_modify_existing_records(self):
        initial = self.run_import()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        for text in ("BASIC5000_0001:変更。\n", "BASIC5000_0001:変更。\nBASIC5000_0002:二。\nEXTRA:余分。\n"):
            with self.subTest(text=text):
                self.transcript.write_text(text, encoding="utf-8")
                result = self.run_import()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mismatch", result.stderr)
                self.assertEqual(self.rows("SELECT subtitle FROM audio_dataset_1 WHERE id=1"), [("水を買います。",)])

    def test_duplicate_transcript_keys_are_rejected(self):
        self.transcript.write_text("BASIC5000_0001:一。\nBASIC5000_0001:二。\n", encoding="utf-8")
        result = self.run_import()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate transcript key", result.stderr)
        self.assertFalse(self.db.exists())

    def test_conflicting_registration_rolls_back(self):
        initial = self.run_import()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        result = self.run_import(name="different")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("registration", result.stderr)
        self.assertEqual(self.rows("SELECT name FROM audio_datasets"), [("basic5000",)])

    def test_invalid_table_suffix_cannot_be_injected(self):
        result = self.run_import(dataset_id="1; DROP TABLE audio_datasets")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.db.exists())

    def test_existing_orphan_table_is_not_adopted_and_registration_rolls_back(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE audio_dataset_1 (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO audio_dataset_1 VALUES (99)")
        result = self.run_import()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unregistered detail table", result.stderr)
        self.assertEqual(self.rows("SELECT id FROM audio_dataset_1"), [(99,)])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name='audio_datasets'"), [])

    def test_second_dataset_gets_its_own_table(self):
        initial = self.run_import()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.root = self.base / "other"
        (self.root / "wav").mkdir(parents=True)
        (self.root / "wav" / "other.wav").write_bytes(b"audio fixture")
        result = self.run_import(with_transcript=False, dataset_id=None, name="other")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["dataset_id"], 2)
        self.assertEqual(self.rows("SELECT audio_name FROM audio_dataset_2"), [("other.wav",)])
        self.assertEqual(self.rows("SELECT count(*) FROM audio_dataset_1"), [(2,)])


if __name__ == "__main__":
    unittest.main()
