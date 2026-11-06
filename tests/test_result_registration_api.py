from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from fastapi.testclient import TestClient

from backend.main import create_app


class ResultRegistrationApiTests(unittest.TestCase):
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
        self.config = {"name": "generated", "storage_dir": str(self.root)}
        self.client = TestClient(create_app(self.base / "test.sqlite3"))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def make_audio(self, name):
        with wave.open(str(self.root / "wav" / name), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 800)

    def register(self, **overrides):
        return self.client.post("/api/datasets/register", json={**self.config, **overrides})

    def assert_no_datasets(self):
        self.assertEqual(self.client.get("/api/datasets").json()["items"], [])

    def test_registers_default_transcript_and_uses_existing_query_and_playback(self):
        response = self.register()
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["import_result"]["registration_status"], "created")
        dataset = result["dataset"]
        self.assertEqual((dataset["id"], dataset["record_count"], dataset["subtitle_count"]), (1, 2, 2))
        self.assertEqual(dataset["transcript_path"], str(self.transcript))
        self.assertEqual(self.client.get("/api/datasets").json()["items"], [dataset])
        records = self.client.get("/api/datasets/1/records").json()["items"]
        self.assertEqual([(item["audio_name"], item["subtitle"]) for item in records], [
            ("000001.wav", "日本語の字幕。"), ("000002.wav", "時刻は12:34です。"),
        ])
        self.assertTrue(all(item["audio_available"] for item in records))
        response = self.client.get("/api/datasets/1/records/1/audio", headers={"Range": "bytes=0-43"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, (self.root / "wav" / "000001.wav").read_bytes()[:44])

    def test_retry_preserves_edited_and_cleared_subtitles_and_record_ids(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.client.patch("/api/datasets/1/records/1", json={"subtitle": "人工校对"}).status_code, 200)
        self.assertEqual(self.client.patch("/api/datasets/1/records/2", json={"subtitle": None}).status_code, 200)
        response = self.register(name=" generated ", transcript_path=str(self.transcript))
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "existing")
        self.assertEqual((result["dataset"]["id"], result["dataset"]["subtitle_count"]), (1, 1))
        self.assertEqual((result["import_result"]["inserted_records"], result["import_result"]["updated_records"]), (0, 0))
        self.assertEqual(result["import_result"]["null_subtitles"], 1)
        records = self.client.get("/api/datasets/1/records").json()["items"]
        self.assertEqual([(item["id"], item["subtitle"]) for item in records], [(1, "人工校对"), (2, None)])
        self.assertEqual(len(self.client.get("/api/datasets").json()["items"]), 1)

    def test_conflicting_name_directory_or_config_returns_409_and_preserves_dataset(self):
        first = self.register()
        self.assertEqual(first.status_code, 201, first.text)
        other = self.base / "other"
        shutil.copytree(self.root, other)
        shutil.copyfile(self.transcript, self.root / "other.txt")
        for config in ({"name": "different"}, {"storage_dir": str(other)}, {"transcript_path": "other.txt"}):
            with self.subTest(config=config):
                response = self.register(**config)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.client.get("/api/datasets").json()["items"], [first.json()["dataset"]])

    def test_changed_file_set_returns_409_without_adding_records(self):
        self.assertEqual(self.register().status_code, 201)
        self.make_audio("000003.wav")
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write("000003:追加。\n")
        response = self.register()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get("/api/datasets/1/records").json()["total"], 2)

    def test_required_transcript_field_rejects_null_and_blank(self):
        for path in (None, "", "  "):
            with self.subTest(path=path):
                response = self.register(transcript_path=path)
                self.assertEqual(response.status_code, 422, response.text)
                self.assert_no_datasets()

    def test_invalid_audio_returns_400_without_partial_dataset(self):
        (self.root / "wav" / "000002.wav").write_bytes(b"broken audio")
        response = self.register()
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("000002.wav", response.json()["detail"])
        self.assert_no_datasets()

    def test_mismatched_subtitles_return_400_without_partial_dataset(self):
        self.transcript.write_text("000001:一文のみ。\n", encoding="utf-8")
        response = self.register()
        self.assertEqual(response.status_code, 400, response.text)
        self.assert_no_datasets()

    def test_transcript_outside_root_returns_400(self):
        outside = self.base / "outside.txt"
        shutil.copyfile(self.transcript, outside)
        response = self.register(transcript_path=str(outside))
        self.assertEqual(response.status_code, 400, response.text)
        self.assert_no_datasets()

    def test_relative_root_returns_400(self):
        response = self.register(storage_dir="relative/result")
        self.assertEqual(response.status_code, 400, response.text)
        self.assert_no_datasets()

    def test_untrusted_origin_cannot_register_results(self):
        response = self.client.post("/api/datasets/register", json=self.config, headers={"Origin": "https://untrusted.example"})
        self.assertEqual(response.status_code, 403)
        self.assert_no_datasets()

    def test_legacy_create_still_rejects_duplicates(self):
        self.assertEqual(self.register().status_code, 201)
        response = self.client.post("/api/datasets", json={**self.config, "transcript_path": self.transcript.name})
        self.assertEqual(response.status_code, 409, response.text)


if __name__ == "__main__":
    unittest.main()
