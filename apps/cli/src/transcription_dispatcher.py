"""Smart multi-provider transcription dispatcher with shared rate limiting.

Manages Groq, AssemblyAI (and future providers) with:
- Per-provider adaptive rate limiting backed by PostgreSQL
- Instant failover on 429 (no long retry loops)
- Automatic chunking for providers with file size limits
- Telemetry logging for every transcription attempt
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.path.insert(0, str(REPO_ROOT / "libs"))
from db import get_connection


# --- Rate Limiter (adapted from analyze_chat.py) ---

class RateLimiter:
    """Per-provider adaptive rate limiter with PostgreSQL persistence."""

    def __init__(self, provider: str, initial_delay: float = 2.0):
        self.provider = provider
        self.delay = initial_delay
        self.min_delay = 0.5
        self.max_delay = 120.0
        self.consecutive_429 = 0
        self.consecutive_ok = 0
        self._load_history()

    def _load_history(self):
        conn = get_connection()
        try:
            recent_429 = conn.execute(
                "SELECT COUNT(*) FROM api_rate_log WHERE provider = %s AND status = '429' "
                "AND timestamp > NOW() - INTERVAL '1 hour'",
                (self.provider,),
            ).fetchone()[0]
            recent_ok = conn.execute(
                "SELECT COUNT(*) FROM api_rate_log WHERE provider = %s AND status = 'ok' "
                "AND timestamp > NOW() - INTERVAL '10 minutes'",
                (self.provider,),
            ).fetchone()[0]

            if recent_429 > 5:
                self.delay = min(self.delay * 2, self.max_delay)
            elif recent_ok > 10 and recent_429 == 0:
                self.delay = max(self.delay * 0.8, self.min_delay)
        finally:
            conn.close()

    def _log(self, status: str, detail: str | None = None):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO api_rate_log (provider, timestamp, status, delay_seconds, error_detail) "
                "VALUES (%s, %s, %s, %s, %s)",
                (self.provider, datetime.now(timezone.utc), status, self.delay, detail),
            )
            conn.commit()
        finally:
            conn.close()

    def record_ok(self):
        self.consecutive_ok += 1
        self.consecutive_429 = 0
        if self.consecutive_ok >= 3:
            self.delay = max(self.delay * 0.9, self.min_delay)
        self._log("ok")

    def record_429(self, detail: str | None = None):
        self.consecutive_429 += 1
        self.consecutive_ok = 0
        self.delay = min(self.delay * (1.5 + self.consecutive_429 * 0.5), self.max_delay)
        self._log("429", detail)

    def record_error(self, detail: str | None = None):
        self._log("error", detail)

    def wait(self):
        if self.delay > 0:
            time.sleep(self.delay)

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_429 < 3


# --- Provider Config ---

@dataclass
class ProviderConfig:
    name: str
    max_file_bytes: int | None  # None = unlimited
    needs_chunking: bool
    chunk_minutes: int
    transcribe_fn: Callable  # (audio_path: str, offset: float) -> list[dict]
    initial_delay: float = 2.0
    available: bool = True


def _is_rate_limit(err: Exception) -> bool:
    s = str(err).lower()
    return "429" in s or "rate_limit" in s or "resource_exhausted" in s


# --- Groq single-file transcription (no retry loop) ---

def _groq_transcribe_chunk(audio_path: str, offset: float = 0.0) -> list[dict]:
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key)
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


# --- AssemblyAI transcription (handles large files natively) ---

def _assemblyai_transcribe(audio_path: str, offset: float = 0.0) -> list[dict]:
    import httpx

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not set")

    headers = {"authorization": api_key}
    base = "https://api.assemblyai.com/v2"

    print(f"    [assemblyai] Uploading...", flush=True)
    with open(audio_path, "rb") as f:
        upload_resp = httpx.post(f"{base}/upload", headers=headers, content=f, timeout=600)
        upload_resp.raise_for_status()
    audio_url = upload_resp.json()["upload_url"]

    resp = httpx.post(f"{base}/transcript", headers=headers, json={
        "audio_url": audio_url,
        "language_code": "es",
        "speech_models": ["universal-2"],
    }, timeout=30)
    resp.raise_for_status()
    transcript_id = resp.json()["id"]
    print(f"    [assemblyai] Transcribing (id={transcript_id})...", flush=True)

    while True:
        time.sleep(5)
        resp = httpx.get(f"{base}/transcript/{transcript_id}", headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "completed":
            break
        elif data["status"] == "error":
            raise RuntimeError(f"AssemblyAI error: {data.get('error')}")

    resp = httpx.get(f"{base}/transcript/{transcript_id}/sentences", headers=headers, timeout=30)
    resp.raise_for_status()
    sentences = resp.json().get("sentences", [])

    segments = [
        {"start": s["start"] / 1000 + offset, "end": s["end"] / 1000 + offset, "text": s["text"].strip()}
        for s in sentences
    ]
    print(f"    [assemblyai] {len(segments)} segments", flush=True)
    return segments


# --- Dispatcher ---

class TranscriptionDispatcher:
    """Smart multi-provider transcription with shared rate limiting."""

    def __init__(self):
        self.providers: list[ProviderConfig] = []
        self.limiters: dict[str, RateLimiter] = {}
        self._register_defaults()

    def _register_defaults(self):
        if os.environ.get("GROQ_API_KEY"):
            self.register(ProviderConfig(
                name="groq",
                max_file_bytes=24 * 1024 * 1024,
                needs_chunking=True,
                chunk_minutes=20,
                transcribe_fn=_groq_transcribe_chunk,
                initial_delay=2.0,
            ))
        if os.environ.get("ASSEMBLYAI_API_KEY"):
            self.register(ProviderConfig(
                name="assemblyai",
                max_file_bytes=None,
                needs_chunking=False,
                chunk_minutes=0,
                transcribe_fn=_assemblyai_transcribe,
                initial_delay=1.0,
            ))

    def register(self, config: ProviderConfig):
        self.providers.append(config)
        self.limiters[config.name] = RateLimiter(
            config.name, initial_delay=config.initial_delay,
        )

    def transcribe(self, audio_path: str) -> tuple[list[dict], str]:
        """Transcribe audio, auto-selecting provider. Returns (segments, provider_name)."""
        file_size = os.path.getsize(audio_path)

        for provider in self.providers:
            limiter = self.limiters[provider.name]
            if not limiter.is_healthy:
                print(f"  Skipping {provider.name} (unhealthy, delay={limiter.delay:.0f}s)", flush=True)
                continue

            try:
                if provider.needs_chunking and provider.max_file_bytes and file_size > provider.max_file_bytes:
                    segments = self._transcribe_chunked(audio_path, provider, limiter)
                else:
                    print(f"  [{provider.name}] Transcribing ({file_size / 1e6:.1f} MB)...", flush=True)
                    segments = provider.transcribe_fn(audio_path, 0.0)
                    limiter.record_ok()

                return segments, provider.name

            except Exception as e:
                if _is_rate_limit(e):
                    limiter.record_429(str(e)[:200])
                    print(f"  [{provider.name}] Rate limited → trying next provider", flush=True)
                    continue
                else:
                    limiter.record_error(str(e)[:200])
                    raise

        # All providers exhausted — wait for the best one and retry once
        best = self._best_provider()
        if best:
            limiter = self.limiters[best.name]
            wait = min(limiter.delay, 60)
            print(f"  All providers exhausted. Waiting {wait:.0f}s for {best.name}...", flush=True)
            time.sleep(wait)
            limiter.consecutive_429 = 0
            return self.transcribe(audio_path)

        raise RuntimeError("No transcription providers available")

    def _transcribe_chunked(self, audio_path: str, provider: ProviderConfig, limiter: RateLimiter) -> list[dict]:
        """Transcribe a large file by chunking, with per-chunk failover."""
        from transcribe_groq import segment_audio

        print(f"  [{provider.name}] File too large, segmenting into {provider.chunk_minutes}-min chunks...", flush=True)

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = segment_audio(audio_path, tmpdir)
            print(f"  {len(chunks)} segments created", flush=True)

            all_segments = []
            for i, (chunk_path, offset) in enumerate(chunks):
                chunk_size = os.path.getsize(chunk_path)
                label = f"  [{i + 1}/{len(chunks)}]"

                transcribed = False
                for prov in [provider] + [p for p in self.providers if p.name != provider.name]:
                    plim = self.limiters[prov.name]
                    if not plim.is_healthy:
                        continue

                    try:
                        if prov.needs_chunking:
                            print(f"{label} [{prov.name}] ({chunk_size / 1e6:.1f} MB, offset {offset:.0f}s)...", flush=True)
                            segs = prov.transcribe_fn(chunk_path, offset)
                        else:
                            if i == 0:
                                print(f"{label} [{prov.name}] Sending full file ({os.path.getsize(audio_path) / 1e6:.1f} MB)...", flush=True)
                                segs = prov.transcribe_fn(audio_path, 0.0)
                                plim.record_ok()
                                return segs
                            else:
                                print(f"{label} [{prov.name}] Switching to full-file transcription...", flush=True)
                                segs = prov.transcribe_fn(audio_path, 0.0)
                                plim.record_ok()
                                return segs

                        plim.record_ok()
                        all_segments.extend(segs)
                        transcribed = True
                        plim.wait()
                        break

                    except Exception as e:
                        if _is_rate_limit(e):
                            plim.record_429(str(e)[:200])
                            print(f"{label} [{prov.name}] Rate limited → trying next", flush=True)
                            continue
                        else:
                            plim.record_error(str(e)[:200])
                            raise

                if not transcribed:
                    best = self._best_provider()
                    if best:
                        wait = min(self.limiters[best.name].delay, 60)
                        print(f"  All providers exhausted on chunk {i + 1}. Waiting {wait:.0f}s...", flush=True)
                        time.sleep(wait)
                        self.limiters[best.name].consecutive_429 = 0
                        segs = best.transcribe_fn(chunk_path if best.needs_chunking else audio_path, offset if best.needs_chunking else 0.0)
                        self.limiters[best.name].record_ok()
                        if not best.needs_chunking:
                            return segs
                        all_segments.extend(segs)

            return all_segments

    def _best_provider(self) -> ProviderConfig | None:
        """Pick the provider with the shortest delay."""
        available = [p for p in self.providers if p.available]
        if not available:
            return None
        return min(available, key=lambda p: self.limiters[p.name].delay)
