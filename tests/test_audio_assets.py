from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave

from fastapi.testclient import TestClient

from backend.main import create_app
from import_dataset import import_dataset


class AudioAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.db = self.base / 'test.sqlite3'
        self.audio = self.base / '日本語.wav'
        with wave.open(str(self.audio), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b'\x00\x00' * 8000)
        self.config = dict(name='長い録音', file_path=str(self.audio), kind='source')
        self.client = TestClient(create_app(self.db))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def create(self, **overrides):
        return self.client.post('/api/audios', json={**self.config, **overrides})

    def test_registers_single_audio_with_metadata_and_retrieves_it_by_id(self):
        original = self.audio.read_bytes()
        response = self.create()
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        self.assertEqual((row['id'], row['kind'], row['file_path']), (1, 'source', str(self.audio)))
        self.assertEqual((row['duration_seconds'], row['sample_rate'], row['channels']), (0.5, 16000, 1))
        self.assertEqual(row['size_bytes'], len(original))
        self.assertTrue(row['file_available'])
        self.assertEqual(self.client.get('/api/audios/1').json(), row)
        self.assertEqual(self.client.get('/api/audios').json()['items'], [row])
        self.assertEqual(self.audio.read_bytes(), original)

    def test_reference_metadata_is_optional_and_editable_with_exclusive_kind(self):
        response = self.create(kind='reference', speaker='井上', language='ja', reference_text='時刻は12:34です。', notes='テスト')
        self.assertEqual(response.status_code, 201, response.text)
        config = {**self.config, 'kind': 'reference', 'reference_text': '修订文本', 'speaker': '井上', 'language': 'ja', 'notes': None}
        response = self.client.put('/api/audios/1', json=config)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['reference_text'], '修订文本')
        self.assertEqual(response.json()['kind'], 'reference')
        response = self.client.put('/api/audios/1', json=self.config)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['kind'], 'source')
        self.assertIsNone(response.json()['reference_text'])

    def test_invalid_fields_never_create_records(self):
        for config in ({'kind': 'both'}, {'kind': ['source', 'reference']}, {'kind': None}, {'name': '  '}, {'file_path': ''}):
            with self.subTest(config=config):
                response = self.create(**config)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get('/api/audios').json()['total'], 0)

    def test_duplicate_path_including_alias_returns_409(self):
        first = self.create()
        self.assertEqual(first.status_code, 201, first.text)
        alias = self.base / 'alias.wav'
        alias.symlink_to(self.audio)
        for path in (self.audio, alias):
            response = self.create(name='別の名前', file_path=str(path), kind='reference')
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get('/api/audios').json()['total'], 1)

    def test_search_filter_pagination_and_literal_search(self):
        self.assertEqual(self.create().status_code, 201)
        second = self.base / 'second.wav'
        shutil.copyfile(self.audio, second)
        self.assertEqual(self.create(name='参考100%_音声', file_path=str(second), kind='reference', speaker='Alice').status_code, 201)
        self.assertEqual(self.client.get('/api/audios?kind=source').json()['total'], 1)
        self.assertEqual(self.client.get('/api/audios?kind=reference').json()['items'][0]['name'], '参考100%_音声')
        for q, total in (('Alice', 1), ('100%_', 1), ("' OR 1=1 --", 0)):
            self.assertEqual(self.client.get('/api/audios', params={'q': q}).json()['total'], total)
        page = self.client.get('/api/audios?page=2&page_size=1').json()
        self.assertEqual((page['total'], page['items'][0]['id']), (2, 1))
        self.assertEqual(self.client.get('/api/audios?kind=both').status_code, 422)
        self.assertEqual(self.client.get('/api/audios?page=0').status_code, 422)

    def test_bad_paths_and_non_audio_are_rejected_without_partial_registration(self):
        bad = self.base / 'bad.wav'
        bad.write_bytes(b'not an audio file')
        for path in ('relative.wav', 'https://example.com/a.wav', str(self.base), str(self.base / 'missing.wav'), str(bad)):
            with self.subTest(path=path):
                response = self.create(file_path=path)
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get('/api/audios').json()['total'], 0)

    def test_m4a_metadata_and_range_playback(self):
        m4a = self.base / 'long.m4a'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.audio), '-c:a', 'aac', str(m4a)], check=True)
        response = self.create(file_path=str(m4a))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertGreater(response.json()['duration_seconds'], 0)
        response = self.client.get('/api/audios/1/file', headers={'Range': 'bytes=0-31'})
        self.assertEqual(response.status_code, 206, response.text)
        self.assertEqual(response.content, m4a.read_bytes()[:32])
        self.assertIn('audio/mp4', response.headers['content-type'])

    def test_missing_file_remains_listed_and_can_be_repaired(self):
        self.assertEqual(self.create().status_code, 201)
        replacement = self.base / 'moved.wav'
        self.audio.rename(replacement)
        row = self.client.get('/api/audios/1').json()
        self.assertFalse(row['file_available'])
        self.assertEqual(self.client.get('/api/audios/1/file').status_code, 404)
        response = self.client.put('/api/audios/1', json={**self.config, 'file_path': str(replacement)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['file_available'])

    def test_retargeted_symlink_is_not_streamed(self):
        self.assertEqual(self.create().status_code, 201)
        private = self.base / 'private.wav'
        private.write_bytes(b'private')
        self.audio.unlink()
        self.audio.symlink_to(private)
        self.assertFalse(self.client.get('/api/audios/1').json()['file_available'])
        self.assertEqual(self.client.get('/api/audios/1/file').status_code, 409)

    def test_failed_update_preserves_metadata(self):
        first = self.create()
        self.assertEqual(first.status_code, 201, first.text)
        response = self.client.put('/api/audios/1', json={**self.config, 'file_path': str(self.base / 'missing.wav'), 'name': '失敗'})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get('/api/audios/1').json(), first.json())

    def test_unregister_only_removes_index_and_preserves_audio(self):
        self.assertEqual(self.create().status_code, 201)
        response = self.client.delete('/api/audios/1')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.audio.is_file())
        self.assertEqual(self.client.get('/api/audios').json()['total'], 0)
        self.assertEqual(self.client.get('/api/audios/1').status_code, 404)
        self.assertEqual(self.client.delete('/api/audios/1').status_code, 404)

    def test_data_persists_across_restarts_and_dataset_features_still_work(self):
        root = self.base / 'dataset'
        (root / 'wav').mkdir(parents=True)
        shutil.copyfile(self.audio, root / 'wav/a.wav')
        import_dataset(db=self.db, name='dataset', root=root)
        self.assertEqual(self.create().status_code, 201)
        with TestClient(create_app(self.db)) as restarted:
            self.assertEqual(restarted.get('/api/audios/1').json()['kind'], 'source')
            self.assertEqual(restarted.get('/api/datasets').json()['items'][0]['record_count'], 1)
            self.assertEqual(restarted.get('/api/datasets/1/records/1/audio').status_code, 200)

    def test_untrusted_origins_cannot_register_edit_or_unregister(self):
        for method, path in (('POST', '/api/audios'), ('PUT', '/api/audios/1'), ('DELETE', '/api/audios/1')):
            response = self.client.request(method, path, json=self.config, headers={'Origin': 'https://untrusted.example'})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/api/audios').json()['total'], 0)

    def test_unknown_and_invalid_ids(self):
        self.assertEqual(self.client.get('/api/audios/999').status_code, 404)
        self.assertEqual(self.client.get('/api/audios/0').status_code, 422)
        self.assertEqual(self.client.get('/api/audios/999/file').status_code, 404)

    def test_removed_ids_are_never_reused_for_an_unrelated_audio(self):
        first = self.create()
        self.assertEqual(first.status_code, 201, first.text)
        old_id = first.json()['id']
        self.assertEqual(self.client.delete(f'/api/audios/{old_id}').status_code, 200)
        other = self.base / 'other.wav'
        shutil.copyfile(self.audio, other)
        second = self.create(file_path=str(other), kind='reference')
        self.assertEqual(second.status_code, 201, second.text)
        self.assertGreater(second.json()['id'], old_id)
        self.assertEqual(self.client.get(f'/api/audios/{old_id}').status_code, 404)
        self.assertEqual(self.client.get(f'/api/audios/{old_id}/file').status_code, 404)

    def test_updating_to_a_registered_path_keeps_both_records(self):
        first = self.create()
        self.assertEqual(first.status_code, 201)
        other = self.base / 'other.wav'
        shutil.copyfile(self.audio, other)
        second = self.create(file_path=str(other), kind='reference')
        self.assertEqual(second.status_code, 201)
        response = self.client.put('/api/audios/2', json=self.config)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get('/api/audios/1').json(), first.json())
        self.assertEqual(self.client.get('/api/audios/2').json(), second.json())


if __name__ == '__main__':
    unittest.main()
