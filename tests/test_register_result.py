from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from register_result import register_result, validate_pcm_wav


SCRIPT = Path(__file__).resolve().parents[1] / "register_result.py"


class RegisterResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "result"
        (self.root / "wav").mkdir(parents=True)
        self.make_audio("000001.wav")
        self.make_audio("000002.wav")
        self.transcript = self.root / "transcript_utf8.txt"
        self.transcript.write_text("000001:日本語の字幕。\n000002:時刻は12:34です。\n", encoding="utf-8")
        self.db = self.base / "datasets.sqlite3"

    def make_audio(self, name, *, frames=4000):
        with wave.open(str(self.root / "wav" / name), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * frames)

    def register(self, *, name="generated", extra=()):
        return subprocess.run([
            sys.executable, str(SCRIPT), "--db", str(self.db),
            "--name", name, "--root", str(self.root), *extra,
        ], text=True, capture_output=True)

    def rows(self, sql):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute(sql).fetchall()

    def test_cli_registers_pcm_and_matching_text_without_changing_files(self):
        (self.root / "wav" / "000001.srt").write_text("optional sidecar", encoding="utf-8")
        (self.root / "process.jsonl").write_text('{"stage":"done"}\n', encoding="utf-8")
        files = [p for p in self.root.rglob("*") if p.is_file()]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        response = self.register()
        self.assertEqual(response.returncode, 0, response.stderr)
        result = json.loads(response.stdout)
        self.assertEqual((result["registration_status"], result["dataset_id"], result["total_records"]), ("created", 1, 2))
        self.assertEqual(self.rows("SELECT id,audio_name,subtitle FROM audio_dataset_1 ORDER BY id"), [
            (1, "000001.wav", "日本語の字幕。"), (2, "000002.wav", "時刻は12:34です。"),
        ])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_repeated_registration_preserves_manual_subtitles_and_ids(self):
        initial = self.register()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE audio_dataset_1 SET subtitle='人工校对' WHERE id=1")
            conn.execute("UPDATE audio_dataset_1 SET subtitle=NULL WHERE id=2")
        response = self.register()
        self.assertEqual(response.returncode, 0, response.stderr)
        result = json.loads(response.stdout)
        self.assertEqual(result["registration_status"], "existing")
        self.assertEqual((result["inserted_records"], result["updated_records"], result["unchanged_records"], result["null_subtitles"]), (0, 0, 2, 1))
        self.assertEqual(self.rows("SELECT id,subtitle FROM audio_dataset_1 ORDER BY id"), [(1, "人工校对"), (2, None)])
        self.assertEqual(self.rows("SELECT count(*) FROM audio_datasets"), [(1,)])

    def test_registration_conflict_preserves_existing_dataset(self):
        initial = self.register()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        response = self.register(name="different")
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(self.rows("SELECT name FROM audio_datasets"), [("generated",)])
        self.assertEqual(self.rows("SELECT count(*) FROM audio_dataset_1"), [(2,)])

    def test_changed_file_set_is_not_silently_added_on_retry(self):
        initial = self.register()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.make_audio("000003.wav")
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write("000003:新しい文。\n")
        response = self.register()
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(self.rows("SELECT id,audio_name FROM audio_dataset_1 ORDER BY id"), [(1, "000001.wav"), (2, "000002.wav")])

    def test_concurrent_registration_returns_one_dataset(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.register(), range(2)))
        for response in responses:
            self.assertEqual(response.returncode, 0, response.stderr)
        results = [json.loads(response.stdout) for response in responses]
        self.assertEqual(sorted(result["registration_status"] for result in results), ["created", "existing"])
        self.assertEqual([result["dataset_id"] for result in results], [1, 1])
        self.assertEqual(self.rows("SELECT count(*) FROM audio_datasets"), [(1,)])
        self.assertEqual(self.rows("SELECT count(*) FROM audio_dataset_1"), [(2,)])

    def test_invalid_empty_and_truncated_audio_are_rejected_before_database_creation(self):
        audio = self.root / "wav" / "000002.wav"
        for kind in ("invalid", "empty", "truncated"):
            with self.subTest(kind=kind):
                self.make_audio("000002.wav", frames=0 if kind == "empty" else 4000)
                if kind == "invalid":
                    audio.write_bytes(b"not a WAV file")
                elif kind == "truncated":
                    audio.write_bytes(audio.read_bytes()[:-1])
                response = self.register()
                self.assertNotEqual(response.returncode, 0, response.stdout)
                self.assertIn("000002.wav", response.stderr)
                self.assertFalse(self.db.exists())

    def test_audio_symlink_outside_audio_directory_is_rejected(self):
        audio = self.root / "wav" / "000001.wav"
        outside = self.root / "outside.wav"
        audio.rename(outside)
        audio.symlink_to(outside)
        response = self.register()
        self.assertNotEqual(response.returncode, 0, response.stdout)
        self.assertFalse(self.db.exists())

    def test_transcript_outside_dataset_root_is_rejected_including_symlinks(self):
        outside = self.base / "outside.txt"
        self.transcript.rename(outside)
        self.transcript.symlink_to(outside)
        for path in (str(outside), self.transcript.name):
            with self.subTest(path=path):
                response = self.register(extra=("--transcript", path))
                self.assertNotEqual(response.returncode, 0, response.stdout)
                self.assertFalse(self.db.exists())

    def test_missing_mismatched_and_empty_subtitles_do_not_register_partial_results(self):
        for contents in (None, "000001:一文。\n", "000001: \n000002:字幕。\n"):
            with self.subTest(contents=contents):
                if contents is None:
                    self.transcript.unlink()
                else:
                    self.transcript.write_text(contents, encoding="utf-8")
                response = self.register()
                self.assertNotEqual(response.returncode, 0, response.stdout)
                self.assertFalse(self.db.exists())

    def test_python_entry_point_requires_transcript(self):
        for transcript in (None, "", "  "):
            with self.subTest(transcript=transcript):
                with self.assertRaises(ValueError):
                    register_result(db=self.db, name="generated", root=self.root, transcript=transcript)
                self.assertFalse(self.db.exists())

    def test_failed_validation_preserves_registered_records(self):
        initial = self.register()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE audio_dataset_1 SET subtitle='人工校对' WHERE id=1")
        (self.root / "wav" / "000002.wav").write_bytes(b"broken")
        response = self.register()
        self.assertNotEqual(response.returncode, 0, response.stdout)
        self.assertEqual(self.rows("SELECT id,subtitle FROM audio_dataset_1 ORDER BY id"), [
            (1, "人工校对"), (2, "時刻は12:34です。"),
        ])

    def test_partial_pcm_frame_and_its_truncated_payload_are_rejected(self):
        audio = self.root / "wav" / "000002.wav"
        for actual_bytes in (3, 2):
            with self.subTest(actual_bytes=actual_bytes):
                self.make_audio("000002.wav", frames=1)
                contents = bytearray(audio.read_bytes())
                contents[4:8] = (39).to_bytes(4, "little")
                contents[40:44] = (3).to_bytes(4, "little")
                audio.write_bytes(contents + b"\x00" * (actual_bytes - 2))
                response = self.register()
                self.assertNotEqual(response.returncode, 0, response.stdout)
                self.assertIn("000002.wav", response.stderr)
                self.assertFalse(self.db.exists())

    def test_registration_never_inserts_files_added_after_validation_begins(self):
        outside = self.base / "not_audio.bin"
        outside.write_bytes(b"not audio")
        extra = self.root / "wav" / "000003.wav"

        def validate_and_publish(path):
            validate_pcm_wav(path)
            if not extra.exists():
                extra.symlink_to(outside)
                with self.transcript.open("a", encoding="utf-8") as handle:
                    handle.write("000003:未校验的音频。\n")

        # Deterministically schedule another exporter while reading real files.
        with patch("register_result.validate_pcm_wav", side_effect=validate_and_publish):
            result = register_result(db=self.db, name="generated", root=self.root)
        self.assertEqual(result["total_records"], 2)
        self.assertEqual(self.rows("SELECT audio_name FROM audio_dataset_1 ORDER BY id"), [
            ("000001.wav",), ("000002.wav",),
        ])

    def test_large_wav_with_padded_metadata_chunk_is_supported(self):
        self.make_audio("000001.wav", frames=600000)
        audio = self.root / "wav" / "000001.wav"
        contents = bytearray(audio.read_bytes())
        metadata = b"JUNK\x03\x00\x00\x00abc\x00"
        contents[4:8] = (len(contents) - 8 + len(metadata)).to_bytes(4, "little")
        audio.write_bytes(contents[:36] + metadata + contents[36:])
        response = self.register()
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(json.loads(response.stdout)["total_records"], 2)


if __name__ == "__main__":
    unittest.main()
