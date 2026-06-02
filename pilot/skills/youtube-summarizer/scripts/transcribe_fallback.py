#!/usr/bin/env python3
"""
Local YouTube transcription fallback using faster-whisper.

This module can be imported (no stdout noise) or run standalone.
When imported, use transcribe_video() directly.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def transcribe_video(
    video_id: str,
    *,
    model_size: str = "base",
    language: str | None = None,
    keep_audio: bool = False,
) -> dict:
    """Download audio, transcribe locally with Whisper, return transcript metadata.

    Returns a dict compatible with the youtube_summarizer payload format:
    {
        "full_text": str,
        "snippet_count": int,
        "duration_seconds": float,
        "language": str,
        "language_code": str,
        "is_generated": bool,
        "character_count": int,
        "source": "whisper",
        "whisper_model": str,
    }

    Logs progress to stderr only; stdout is kept clean for JSON piping.
    """
    skill_dir = Path(__file__).resolve().parent.parent
    transcripts_dir = skill_dir / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix="yt_transcribe_")
    raw_audio = os.path.join(tmpdir, f"{video_id}_raw")
    wav_path = os.path.join(tmpdir, f"{video_id}.wav")

    try:
        print(f"[fallback] Downloading audio for {video_id}...", file=sys.stderr)
        _download_audio(video_id, raw_audio)

        downloaded = _find_downloaded_file(tmpdir, f"{video_id}_raw")
        if not downloaded:
            raise RuntimeError("yt-dlp did not produce an output file")

        print("[fallback] Converting to WAV...", file=sys.stderr)
        _convert_to_wav(downloaded, wav_path)

        print(f"[fallback] Transcribing with Whisper ({model_size})...", file=sys.stderr)
        transcript_text, detected_lang = _transcribe(wav_path, model_size=model_size, language=language)

        out_file = transcripts_dir / f"{video_id}.txt"
        out_file.write_text(transcript_text, encoding="utf-8")
        print(f"[fallback] Saved transcript to: {out_file}", file=sys.stderr)

        if keep_audio:
            keep_path = transcripts_dir / f"{video_id}.wav"
            os.rename(wav_path, str(keep_path))
            print(f"[fallback] Kept audio: {keep_path}", file=sys.stderr)

        # Estimate duration from last timestamp line if present
        duration_seconds = _estimate_duration_from_text(transcript_text)
        lines = [line for line in transcript_text.splitlines() if line.strip() and not line.startswith("#")]

        return {
            "full_text": transcript_text,
            "snippet_count": len(lines),
            "duration_seconds": duration_seconds,
            "language": _language_name(detected_lang),
            "language_code": detected_lang or "",
            "is_generated": True,
            "character_count": len(transcript_text),
            "source": "whisper",
            "whisper_model": model_size,
        }
    finally:
        if not keep_audio:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        else:
            import shutil
            for f in os.listdir(tmpdir):
                if not f.endswith(".wav"):
                    p = os.path.join(tmpdir, f)
                    if os.path.isfile(p):
                        os.remove(p)


def _download_audio(video_id: str, output_path: str) -> None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "--quiet",
        "--no-warnings",
        "-f", "bestaudio/best",
        "-o", output_path,
        url,
    ]
    subprocess.run(cmd, check=True)


def _find_downloaded_file(tmpdir: str, prefix: str) -> str | None:
    for f in os.listdir(tmpdir):
        if f.startswith(prefix):
            return os.path.join(tmpdir, f)
    return None


def _convert_to_wav(input_path: str, output_wav: str) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        output_wav,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _transcribe(wav_path: str, model_size: str, language: str | None) -> tuple[str, str | None]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(wav_path, language=language, beam_size=5)

    lines = []
    detected = info.language if info.language else None
    if detected:
        lines.append(f"# Detected language: {detected} (probability: {info.language_probability:.2f})")
    lines.append("")

    for segment in segments:
        start = _format_time(segment.start)
        end = _format_time(segment.end)
        lines.append(f"[{start} --> {end}] {segment.text.strip()}")

    return "\n".join(lines), detected


def _format_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{ms:03d}"


def _estimate_duration_from_text(text: str) -> float:
    """Crude duration estimate from the last timestamp in the transcript."""
    last_ts = 0.0
    for line in text.splitlines():
        m = re.search(r"\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})", line)
        if m:
            hrs, mins, secs, ms = map(int, m.groups())
            last_ts = hrs * 3600 + mins * 60 + secs + ms / 1000.0
    return last_ts


def _language_name(code: str | None) -> str:
    """Return a human-readable language name if known."""
    mapping = {
        "en": "English",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "pl": "Polish",
        "ru": "Russian",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
        "ar": "Arabic",
        "hi": "Hindi",
        "tr": "Turkish",
    }
    return mapping.get(code or "", code or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe YouTube videos locally with Whisper.")
    parser.add_argument("video", help="YouTube URL or video ID")
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument("--language", default=None, help="Force language code, e.g. de or en")
    parser.add_argument("--keep-audio", action="store_true", help="Keep downloaded audio file")
    args = parser.parse_args()

    video_id = _extract_video_id(args.video)
    result = transcribe_video(
        video_id,
        model_size=args.model,
        language=args.language,
        keep_audio=args.keep_audio,
    )
    print(result["full_text"])
    return 0


def _extract_video_id(value: str) -> str:
    patterns = [
        r"(?:v=|/)([0-9A-Za-z_-]{11})",
        r"youtu\.be/([0-9A-Za-z_-]{11})",
        r"youtube\.com/shorts/([0-9A-Za-z_-]{11})",
        r"youtube\.com/embed/([0-9A-Za-z_-]{11})",
        r"youtube\.com/live/([0-9A-Za-z_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, value)
        if m:
            return m.group(1)
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", value):
        return value
    raise ValueError(f"Could not extract video ID from: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
