#!/usr/bin/env python3
"""Register completed WAV/text results without overwriting existing records."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import wave

from import_dataset import DEFAULT_DB, import_dataset


def wav_data_size(source):
    """Read RIFF chunk sizes without wave.getnframes() rounding partial frames."""
    header = source.read(12)
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
        raise wave.Error("Expected a RIFF/WAVE header")
    riff_end = 8 + int.from_bytes(header[4:8], "little")
    file_end = source.seek(0, 2)
    if riff_end > file_end:
        raise wave.Error("Truncated RIFF data")
    source.seek(12)
    while source.tell() + 8 <= riff_end:
        chunk = source.read(8)
        if len(chunk) != 8:
            break
        size = int.from_bytes(chunk[4:], "little")
        if source.tell() + size > riff_end:
            raise wave.Error("Truncated WAV chunk")
        if chunk[:4] == b"data":
            return size
        source.seek(size + size % 2, 1)
    raise wave.Error("Missing WAV data chunk")


def validate_pcm_wav(path):
    """Read declared PCM frames in bounded chunks, detecting incomplete exports."""
    try:
        with path.open("rb") as source:
            data_size = wav_data_size(source)
            source.seek(0)
            with wave.open(source, "rb") as audio:
                frame_size = audio.getnchannels() * audio.getsampwidth()
                remaining = audio.getnframes()
                block_bytes = 1024 * 1024
                if audio.getcomptype() != "NONE" or audio.getframerate() <= 0:
                    raise ValueError(f"Invalid PCM WAV: {path.name}")
                if remaining <= 0 or not 0 < frame_size <= block_bytes:
                    raise ValueError(f"Empty WAV or invalid frame size: {path.name}")
                if data_size % frame_size:
                    raise ValueError(f"Incomplete PCM frame: {path.name}")
                block_frames = block_bytes // frame_size
                while remaining:
                    count = min(block_frames, remaining)
                    if len(audio.readframes(count)) != count * frame_size:
                        raise ValueError(f"Truncated WAV data: {path.name}")
                    remaining -= count
    except (wave.Error, EOFError) as error:
        raise ValueError(f"Invalid PCM WAV: {path.name}: {error}") from error


def validate_result_source(root, audio_subdir, transcript, records):
    """Validate exactly the normalized source snapshot the importer will commit."""
    if transcript is None or not transcript.is_relative_to(root):
        raise ValueError("Transcript must be inside the dataset root")
    directory = (root / audio_subdir).resolve(strict=True)
    for audio_name, _ in records:
        audio = (directory / audio_name).resolve(strict=True)
        if not audio.is_relative_to(directory):
            raise ValueError(f"Audio must be inside the audio directory: {audio_name}")
        validate_pcm_wav(audio)


def register_result(*, db, name, root, audio_subdir="wav", transcript="transcript_utf8.txt"):
    """Create a result dataset, or reuse its registration without syncing text."""
    if transcript is None or not str(transcript).strip():
        raise ValueError("A transcript is required for result registration")
    root = Path(root).expanduser().resolve(strict=True)
    transcript = Path(transcript).expanduser()
    if not transcript.is_absolute():
        transcript = root / transcript
    transcript = transcript.resolve(strict=True)
    if not transcript.is_relative_to(root):
        raise ValueError("Transcript must be inside the dataset root")
    return import_dataset(
        db=db, name=name.strip(), root=root, audio_subdir=audio_subdir,
        transcript=transcript, on_existing="reuse", validate_source=validate_result_source,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--name", required=True, help="Unique dataset name")
    parser.add_argument("--root", type=Path, required=True, help="Completed dataset directory")
    parser.add_argument("--audio-subdir", default="wav", help="Audio directory relative to root")
    parser.add_argument("--transcript", default="transcript_utf8.txt", help="Required UTF-8 key:text file")
    args = parser.parse_args()
    try:
        result = register_result(**vars(args))
    except (OSError, UnicodeError, ValueError, sqlite3.Error) as error:
        print(f"Registration failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
