"""Transcribe audio to SRT using Groq API (primary) or AssemblyAI (fallback).

Groq: Whisper large-v3-turbo, ~50x realtime, 7200s audio/hour free.
AssemblyAI: Proprietary model, ~10x realtime, 100h/month free.

Files >25MB are automatically segmented into 20-min chunks (Groq only).
AssemblyAI handles large files natively.

Usage:
    cd apps/cli && uv run src/transcribe_groq.py <audio_file> [--provider groq|assemblyai]
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = r"D:\bin\ffmpeg.exe"
MAX_FILE_SIZE = 24 * 1024 * 1024  # 24 MB (Groq limit)
SEGMENT_MINUTES = 20


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def get_audio_duration(path: str) -> float:
    result = subprocess.run(
        [FFMPEG, "-i", path],
        capture_output=True, text=True, timeout=30,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if match:
        h, m, s, cs = match.groups()
        return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
    return 0


def segment_audio(audio_path: str, segment_dir: str) -> list[tuple[str, float]]:
    duration = get_audio_duration(audio_path)
    segment_secs = SEGMENT_MINUTES * 60
    segments = []

    if duration <= 0:
        return [(audio_path, 0.0)]

    n_segments = int(duration // segment_secs) + (1 if duration % segment_secs > 0 else 0)

    for i in range(n_segments):
        offset = i * segment_secs
        out_path = os.path.join(segment_dir, f"segment_{i:03d}.opus")
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(offset), "-i", audio_path,
             "-t", str(segment_secs), "-vn", "-acodec", "libopus", "-b:a", "64k", out_path],
            capture_output=True, timeout=120,
        )
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            segments.append((out_path, offset))

    return segments


# --- Groq provider ---

def transcribe_groq_file(client, audio_path: str, offset: float = 0.0, max_retries: int = 3) -> list[dict]:
    for attempt in range(max_retries):
        try:
            with open(audio_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    file=f,
                    model="whisper-large-v3-turbo",
                    language="es",
                    response_format="verbose_json",
                )
            return [
                {"start": seg["start"] + offset, "end": seg["end"] + offset, "text": seg["text"].strip()}
                for seg in result.segments
            ]
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e):
                match = re.search(r"try again in (\d+)m", str(e))
                wait = int(match.group(1)) * 60 + 30 if match else 120
                print(f"    Groq rate limited, esperando {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Groq max retries exceeded")


def transcribe_via_groq(audio_path: str) -> list[dict]:
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key)
    file_size = os.path.getsize(audio_path)

    if file_size <= MAX_FILE_SIZE:
        print("Transcribing via Groq (single request)...", flush=True)
        return transcribe_groq_file(client, audio_path)

    print(f"File too large for Groq, segmenting into {SEGMENT_MINUTES}-min chunks...", flush=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        chunks = segment_audio(audio_path, tmpdir)
        print(f"  {len(chunks)} segments created", flush=True)

        all_segments = []
        for i, (chunk_path, offset) in enumerate(chunks):
            chunk_size = os.path.getsize(chunk_path) / 1024 / 1024
            print(f"  [{i + 1}/{len(chunks)}] Transcribing ({chunk_size:.1f} MB, offset {offset:.0f}s)...", flush=True)
            segs = transcribe_groq_file(client, chunk_path, offset)
            all_segments.extend(segs)
            time.sleep(2)
        return all_segments


# --- AssemblyAI provider ---

def transcribe_via_assemblyai(audio_path: str) -> list[dict]:
    import httpx

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not set")

    headers = {"authorization": api_key}
    base = "https://api.assemblyai.com/v2"

    # Upload audio
    print("Transcribing via AssemblyAI (uploading)...", flush=True)
    with open(audio_path, "rb") as f:
        upload_resp = httpx.post(f"{base}/upload", headers=headers, content=f, timeout=600)
        upload_resp.raise_for_status()
    audio_url = upload_resp.json()["upload_url"]
    print(f"  Uploaded to AssemblyAI CDN", flush=True)

    # Create transcription
    resp = httpx.post(f"{base}/transcript", headers=headers, json={
        "audio_url": audio_url,
        "language_code": "es",
        "speech_models": ["universal-2"],
    }, timeout=30)
    if resp.status_code != 200:
        print(f"  Error {resp.status_code}: {resp.text[:500]}", flush=True)
        resp.raise_for_status()
    transcript_id = resp.json()["id"]
    print(f"  Transcription started (id={transcript_id})", flush=True)

    # Poll until complete
    while True:
        time.sleep(5)
        resp = httpx.get(f"{base}/transcript/{transcript_id}", headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data["status"]
        if status == "completed":
            break
        elif status == "error":
            raise RuntimeError(f"AssemblyAI error: {data.get('error')}")
        print(f"  Status: {status}...", flush=True)

    # Get sentences for better segmentation
    resp = httpx.get(f"{base}/transcript/{transcript_id}/sentences", headers=headers, timeout=30)
    resp.raise_for_status()
    sentences = resp.json().get("sentences", [])

    segments = []
    for sent in sentences:
        segments.append({
            "start": sent["start"] / 1000,
            "end": sent["end"] / 1000,
            "text": sent["text"].strip(),
        })

    print(f"  AssemblyAI returned {len(segments)} segments", flush=True)
    return segments


# --- Main ---

def transcribe(audio_path: str, provider: str = "auto") -> None:
    audio = Path(audio_path)
    srt_path = audio.with_suffix(".srt")
    txt_path = audio.with_suffix(".txt")

    file_size = audio.stat().st_size
    print(f"Audio: {audio_path} ({file_size / 1024 / 1024:.1f} MB)", flush=True)

    t0 = time.time()

    if provider == "auto":
        # Try Groq first, fallback to AssemblyAI on rate limit
        try:
            all_segments = transcribe_via_groq(audio_path)
        except RuntimeError as e:
            if "rate_limit" in str(e).lower() or "retries" in str(e).lower() or "429" in str(e):
                print(f"  Groq failed ({e}), switching to AssemblyAI...", flush=True)
                all_segments = transcribe_via_assemblyai(audio_path)
            else:
                raise
    elif provider == "groq":
        all_segments = transcribe_via_groq(audio_path)
    elif provider == "assemblyai":
        all_segments = transcribe_via_assemblyai(audio_path)
    else:
        sys.exit(f"Unknown provider: {provider}")

    # Write SRT and TXT
    with open(srt_path, "w", encoding="utf-8") as srt_f, \
         open(txt_path, "w", encoding="utf-8") as txt_f:
        for i, seg in enumerate(all_segments, 1):
            start = format_timestamp(seg["start"])
            end = format_timestamp(seg["end"])
            text = seg["text"]
            srt_f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
            txt_f.write(f"[{start}] {text}\n")

    elapsed = time.time() - t0
    duration = all_segments[-1]["end"] if all_segments else 0
    speed = duration / elapsed if elapsed > 0 else 0

    print(f"\nDone! {len(all_segments)} segments in {elapsed:.1f}s ({speed:.0f}x realtime)", flush=True)
    print(f"SRT: {srt_path}", flush=True)
    print(f"TXT: {txt_path}", flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Transcribe audio via Groq or AssemblyAI")
    parser.add_argument("audio_file", help="Path to audio file")
    parser.add_argument("--provider", choices=["auto", "groq", "assemblyai"], default="auto",
                        help="Transcription provider (default: auto — Groq first, AssemblyAI fallback)")
    args = parser.parse_args()
    transcribe(args.audio_file, args.provider)
