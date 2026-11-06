from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
import wave

from fastapi.testclient import TestClient

from import_dataset import import_dataset
from backend.main import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.db = self.base / "test.sqlite3"
        self.root = self.base / "basic"
        self.make_audio(self.root, "A.wav")
        self.make_audio(self.root, "B.wav")
        (self.root / "transcript.txt").write_text("A:日本語の字幕。\nB:もう一つ。\n", encoding="utf-8")
        import_dataset(db=self.db, name="basic", root=self.root, transcript="transcript.txt", dataset_id=1)
        self.client = TestClient(create_app(self.db))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def make_audio(self, root, name):
        (root / "wav").mkdir(parents=True, exist_ok=True)
        with wave.open(str(root / "wav" / name), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 800)

    def test_lists_real_counts_and_dataset_metadata(self):
        response = self.client.get("/api/datasets")
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual((item["name"], item["record_count"], item["subtitle_count"]), ("basic", 2, 2))
        self.assertEqual(item["detail_table"], "audio_dataset_1")
        self.assertTrue(item["storage_available"])

    def test_paginates_searches_and_filters_records(self):
        response = self.client.get("/api/datasets/1/records?page=2&page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["audio_name"], "B.wav")
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["items"][0]["duration_seconds"], 0.05)
        response = self.client.get("/api/datasets/1/records", params={"q": "日本語"})
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(self.client.get("/api/datasets/1/records?subtitle=missing").json()["total"], 0)
        self.assertEqual(self.client.get("/api/datasets/1/records?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/datasets/1/records?page_size=10000").status_code, 422)

    def test_adds_dataset_with_optional_transcript(self):
        root = self.base / "new"
        self.make_audio(root, "NEW.wav")
        response = self.client.post("/api/datasets", json={"name": "new", "storage_dir": str(root)})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["id"], 2)
        item = self.client.get("/api/datasets/2/records").json()["items"][0]
        self.assertIsNone(item["subtitle"])
        self.assertEqual(self.client.get("/api/datasets/2/records?subtitle=missing").json()["total"], 1)

    def test_duplicate_registration_returns_conflict(self):
        response = self.client.post("/api/datasets", json={"name": "basic", "storage_dir": str(self.root)})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.client.get("/api/datasets").json()["items"]), 1)

    def test_updates_configuration_without_overwriting_manual_subtitles(self):
        self.client.patch("/api/datasets/1/records/1", json={"subtitle": "手动修改"})
        response = self.client.put("/api/datasets/1", json={
            "name": "renamed", "storage_dir": str(self.root), "transcript_path": "transcript.txt",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "renamed")
        self.assertEqual(self.client.get("/api/datasets/1/records").json()["items"][0]["subtitle"], "手动修改")

    def test_invalid_configuration_preserves_existing_metadata(self):
        response = self.client.put("/api/datasets/1", json={"name": "oops", "storage_dir": "/path/does/not/exist"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/datasets/1").json()["name"], "basic")

    def test_moving_root_relocates_unchanged_internal_transcript_without_reimport(self):
        self.client.patch("/api/datasets/1/records/1", json={"subtitle": "手动修改"})
        original = self.client.get("/api/datasets/1").json()
        with closing(sqlite3.connect(self.db)) as conn:
            records = conn.execute("SELECT id, audio_name, subtitle FROM audio_dataset_1 ORDER BY id").fetchall()
        moved = self.base / "moved-basic"
        self.root.rename(moved)
        response = self.client.put("/api/datasets/1", json={
            "name": "basic", "storage_dir": f"{moved} ", "audio_subdir": "wav",
            "transcript_path": original["transcript_path"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["storage_dir"], str(moved))
        self.assertEqual(response.json()["transcript_path"], str(moved / "transcript.txt"))
        self.assertEqual(response.json()["record_count"], 2)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT id, audio_name, subtitle FROM audio_dataset_1 ORDER BY id").fetchall(), records)
        self.assertTrue(all(item["audio_available"] for item in self.client.get("/api/datasets/1/records").json()["items"]))
        self.assertEqual(self.client.get("/api/datasets/1/records/1/audio").content[:4], b"RIFF")

    def test_moving_root_preserves_an_unchanged_external_transcript(self):
        external = self.base / "shared-transcript.txt"
        external.write_text((self.root / "transcript.txt").read_text(encoding="utf-8"), encoding="utf-8")
        config = {"name": "basic", "storage_dir": str(self.root), "transcript_path": str(external)}
        self.assertEqual(self.client.put("/api/datasets/1", json=config).status_code, 200)
        moved = self.base / "moved-basic"
        self.root.rename(moved)
        response = self.client.put("/api/datasets/1", json={**config, "storage_dir": str(moved)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["transcript_path"], str(external))

    def test_moving_root_respects_an_explicitly_changed_transcript(self):
        moved = self.base / "moved-basic"
        self.root.rename(moved)
        chosen = self.base / "chosen-transcript.txt"
        chosen.write_text((moved / "transcript.txt").read_text(encoding="utf-8"), encoding="utf-8")
        response = self.client.put("/api/datasets/1", json={
            "name": "basic", "storage_dir": str(moved), "transcript_path": str(chosen),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["transcript_path"], str(chosen))

    def test_missing_transcript_at_new_root_keeps_original_configuration(self):
        original = self.client.get("/api/datasets/1").json()
        moved = self.base / "moved-basic"
        self.make_audio(moved, "A.wav")
        self.make_audio(moved, "B.wav")
        response = self.client.put("/api/datasets/1", json={
            "name": "basic", "storage_dir": str(moved), "transcript_path": original["transcript_path"],
        })
        self.assertEqual(response.status_code, 400, response.text)
        saved = self.client.get("/api/datasets/1").json()
        self.assertEqual(saved["storage_dir"], original["storage_dir"])
        self.assertEqual(saved["transcript_path"], original["transcript_path"])
        self.assertEqual(saved["record_count"], 2)

    def test_edits_and_clears_subtitles_without_writing_source_file(self):
        source = (self.root / "transcript.txt").read_bytes()
        response = self.client.patch("/api/datasets/1/records/1", json={"subtitle": "変更:字幕"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subtitle"], "変更:字幕")
        self.assertEqual((self.root / "transcript.txt").read_bytes(), source)
        response = self.client.patch("/api/datasets/1/records/1", json={"subtitle": "  "})
        self.assertIsNone(response.json()["subtitle"])
        self.assertEqual(self.client.get("/api/datasets/1").json()["subtitle_count"], 1)

    def test_explicit_reimport_syncs_source_and_keeps_record_ids(self):
        self.client.patch("/api/datasets/1/records/1", json={"subtitle": "manual"})
        response = self.client.post("/api/datasets/1/sync")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated_records"], 1)
        item = self.client.get("/api/datasets/1/records").json()["items"][0]
        self.assertEqual((item["id"], item["subtitle"]), (1, "日本語の字幕。"))

    def test_streams_real_wav_and_supports_range_requests(self):
        response = self.client.get("/api/datasets/1/records/1/audio")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:4], b"RIFF")
        response = self.client.get("/api/datasets/1/records/1/audio", headers={"Range": "bytes=0-43"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 44)

    def test_audio_symlinks_cannot_escape_registered_directory(self):
        outside = self.base / "private.wav"
        outside.write_bytes(b"private")
        audio = self.root / "wav" / "A.wav"
        audio.unlink()
        audio.symlink_to(outside)
        response = self.client.get("/api/datasets/1/records/1/audio")
        self.assertEqual(response.status_code, 400)
        response = self.client.get("/api/datasets/1/records")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["items"][0]["audio_available"])

    def test_unknown_ids_and_invalid_ids_return_errors(self):
        self.assertEqual(self.client.get("/api/datasets/999/records").status_code, 404)
        self.assertEqual(self.client.get("/api/datasets/1/records/999/audio").status_code, 404)
        self.assertEqual(self.client.get("/api/datasets/0").status_code, 422)
        self.assertEqual(self.client.get("/api/datasets/1;DROP/records").status_code, 422)

    def test_untrusted_origin_cannot_modify_local_database(self):
        response = self.client.post("/api/datasets/1/sync", headers={"Origin": "https://untrusted.example"})
        self.assertEqual(response.status_code, 403)

    def test_search_metacharacters_are_literal(self):
        for q in ("%", "_", "' OR 1=1 --"):
            self.assertEqual(self.client.get("/api/datasets/1/records", params={"q": q}).json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
