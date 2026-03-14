"""Transcribe audio to SRT using faster-whisper."""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

load_dotenv(REPO_ROOT / ".env")

# Force UTF-8 stdout regardless of Windows locale
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from faster_whisper import WhisperModel


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe(audio_path: str, model_size: str = "medium"):
    audio = Path(audio_path)
    srt_path = audio.with_suffix(".srt")
    txt_path = audio.with_suffix(".txt")

    print(f"Loading model '{model_size}' (CPU)...", flush=True)
    t0 = time.time()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    print(f"Model loaded in {time.time() - t0:.1f}s", flush=True)

    print(f"Transcribing {audio_path} ...", flush=True)
    segments, info = model.transcribe(audio_path, language="es", beam_size=5)

    print(f"Language: {info.language} (prob {info.language_probability:.2f})", flush=True)

    i = 1
    t_start = time.time()

    # Open files for incremental writing
    with open(srt_path, "w", encoding="utf-8") as srt_f, \
         open(txt_path, "w", encoding="utf-8") as txt_f:

        for segment in segments:
            start = format_timestamp(segment.start)
            end = format_timestamp(segment.end)
            text = segment.text.strip()

            srt_f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
            txt_f.write(f"[{start}] {text}\n")

            # Flush to disk every 10 segments
            if i % 10 == 0:
                srt_f.flush()
                txt_f.flush()

            elapsed = time.time() - t_start
            audio_pos = segment.end
            speed = audio_pos / elapsed if elapsed > 0 else 0
            print(f"  [{start}] ({speed:.1f}x realtime) {text[:70]}", flush=True)
            i += 1

    total_time = time.time() - t_start
    print(f"\nDone! {i - 1} segments in {total_time:.0f}s", flush=True)
    print(f"SRT: {srt_path}", flush=True)
    print(f"TXT: {txt_path}", flush=True)


if __name__ == "__main__":
    audio_file = sys.argv[1] if len(sys.argv) > 1 else None
    model = sys.argv[2] if len(sys.argv) > 2 else "medium"

    if not audio_file:
        sys.exit("Usage: uv run transcribe.py <audio_file> [model_size]")

    transcribe(audio_file, model)
