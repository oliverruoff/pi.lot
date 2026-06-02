#!/usr/bin/env python3
"""Fetch a YouTube transcript for agent-side summarization.

This script is intentionally standalone: it has no imports from the host project.
It prints JSON to stdout so any coding agent can consume the transcript and
summarize it with its own model.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception as exc:  # pragma: no cover - dependency may be missing
    YouTubeTranscriptApi = None  # type: ignore[assignment]
    YOUTUBE_TRANSCRIPT_IMPORT_ERROR = str(exc)
else:
    YOUTUBE_TRANSCRIPT_IMPORT_ERROR = ""

try:
    from transcribe_fallback import transcribe_video
    TRANSCRIBE_FALLBACK_AVAILABLE = True
except Exception:  # pragma: no cover
    transcribe_video = None  # type: ignore[assignment]
    TRANSCRIBE_FALLBACK_AVAILABLE = False

VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
DETAIL_LEVELS = {"brief", "standard", "detailed"}
DEFAULT_BUDGETS = {"brief": 12_000, "standard": 30_000, "detailed": 80_000}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a YouTube transcript as JSON.")
    parser.add_argument("video", help="YouTube URL or 11-character video ID")
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_LEVELS),
        default="standard",
        help="Intended summary detail level; controls default transcript budget",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["en"],
        help="Preferred transcript languages in fallback order, e.g. en de",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Maximum transcript characters to return; defaults by detail level",
    )
    parser.add_argument(
        "--transcribe-fallback",
        action="store_true",
        help="If no transcript is available, download audio and transcribe locally with Whisper",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size when using --transcribe-fallback (default: base)",
    )
    parser.add_argument(
        "--whisper-language",
        default=None,
        help="Force language code for Whisper transcription, e.g. de or en",
    )
    args = parser.parse_args()

    try:
        payload = build_payload(
            video=args.video,
            detail=args.detail,
            languages=args.languages,
            max_chars=args.max_chars,
            transcribe_fallback=args.transcribe_fallback,
            whisper_model=args.whisper_model,
            whisper_language=args.whisper_language,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_payload(
    *,
    video: str,
    detail: str,
    languages: list[str],
    max_chars: int | None,
    transcribe_fallback: bool = False,
    whisper_model: str = "base",
    whisper_language: str | None = None,
) -> dict[str, Any]:
    if YouTubeTranscriptApi is None:
        raise RuntimeError(
            "Missing dependency: youtube-transcript-api. Install with: "
            "python -m pip install -r requirements.txt. "
            f"Import error: {YOUTUBE_TRANSCRIPT_IMPORT_ERROR or 'unknown'}"
        )

    video_id = extract_video_id(video)
    if not video_id:
        raise RuntimeError("Could not extract a valid YouTube video ID from input.")

    detail = detail if detail in DETAIL_LEVELS else "standard"
    language_codes = normalize_language_codes(languages)
    transcript = fetch_transcript(
        video_id,
        language_codes,
        transcribe_fallback=transcribe_fallback,
        whisper_model=whisper_model,
        whisper_language=whisper_language,
    )

    budget = max_chars if max_chars and max_chars > 0 else DEFAULT_BUDGETS[detail]
    transcript_text = truncate_middle(str(transcript["full_text"]), budget)
    was_truncated = len(str(transcript["full_text"])) > len(transcript_text)

    return {
        "ok": True,
        "video": {
            "input": video,
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
        },
        "detail_level": detail,
        "summary_instruction": summary_instruction(detail),
        "transcript": {
            "language": transcript["language"],
            "language_code": transcript["language_code"],
            "is_generated": transcript["is_generated"],
            "snippet_count": transcript["snippet_count"],
            "duration_seconds": transcript["duration_seconds"],
            "character_count": transcript["character_count"],
            "returned_character_count": len(transcript_text),
            "was_truncated": was_truncated,
        },
        "transcript_text": transcript_text,
    }


def fetch_transcript(
    video_id: str,
    languages: list[str],
    *,
    transcribe_fallback: bool = False,
    whisper_model: str = "base",
    whisper_language: str | None = None,
) -> dict[str, Any]:
    api = YouTubeTranscriptApi()

    try:
        fetched = api.fetch(video_id, languages=languages)
        snippets, full_text, duration = normalize_fetched_snippets(fetched)
        return {
            "snippets": snippets,
            "full_text": full_text,
            "snippet_count": len(snippets),
            "duration_seconds": duration,
            "language": safe_str(getattr(fetched, "language", "")),
            "language_code": safe_str(getattr(fetched, "language_code", "")),
            "is_generated": bool(getattr(fetched, "is_generated", False)),
            "character_count": len(full_text),
            "source": "youtube_transcript_api",
        }
    except AttributeError:
        # Compatibility fallback for older youtube-transcript-api versions.
        pass
    except Exception as exc:
        if transcribe_fallback:
            return _try_transcribe_fallback(
                video_id, exc, whisper_model=whisper_model, whisper_language=whisper_language
            )
        raise transcript_error(exc, fallback_available=transcribe_fallback) from exc

    try:
        raw_entries = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    except Exception as exc:
        if transcribe_fallback:
            return _try_transcribe_fallback(
                video_id, exc, whisper_model=whisper_model, whisper_language=whisper_language
            )
        raise transcript_error(exc, fallback_available=transcribe_fallback) from exc

    snippets = normalize_raw_entries(raw_entries)
    full_text = "\n".join(item["text"] for item in snippets if item["text"])
    return {
        "snippets": snippets,
        "full_text": full_text,
        "snippet_count": len(snippets),
        "duration_seconds": estimate_duration_seconds(snippets),
        "language": "",
        "language_code": "",
        "is_generated": False,
        "character_count": len(full_text),
        "source": "youtube_transcript_api",
    }


def _try_transcribe_fallback(
    video_id: str,
    original_exc: Exception,
    *,
    whisper_model: str = "base",
    whisper_language: str | None = None,
) -> dict[str, Any]:
    if not TRANSCRIBE_FALLBACK_AVAILABLE:
        raise transcript_error(
            original_exc,
            fallback_available=False,
            fallback_reason="transcribe_fallback dependencies not installed",
        ) from original_exc
    try:
        return transcribe_video(
            video_id,
            model_size=whisper_model,
            language=whisper_language,
        )
    except Exception as fallback_exc:
        raise transcript_error(
            original_exc,
            fallback_available=True,
            fallback_reason=str(fallback_exc),
        ) from fallback_exc


def transcript_error(
    exc: Exception,
    *,
    fallback_available: bool = False,
    fallback_reason: str = "",
) -> RuntimeError:
    name = exc.__class__.__name__
    base_msg = ""
    if name in {"TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable"}:
        base_msg = f"No usable transcript for this video ({name})."
    elif name in {"RequestBlocked", "IpBlocked"}:
        base_msg = "YouTube blocked transcript requests from this environment."
    else:
        base_msg = f"Failed to fetch YouTube transcript ({name}): {exc}"

    if fallback_available:
        base_msg += f" Local transcription fallback also failed: {fallback_reason}"
    return RuntimeError(base_msg)


def extract_video_id(value: str) -> str:
    text = str(value or "").strip()
    if VIDEO_ID_RE.fullmatch(text):
        return text

    parsed = urlparse(text)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path.split("/")[0].strip()
        return candidate if VIDEO_ID_RE.fullmatch(candidate) else ""

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if path == "watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0].strip()
            return candidate if VIDEO_ID_RE.fullmatch(candidate) else ""
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
            candidate = parts[1].strip()
            return candidate if VIDEO_ID_RE.fullmatch(candidate) else ""

    return ""


def normalize_fetched_snippets(fetched: Any) -> tuple[list[dict[str, Any]], str, float]:
    snippets = []
    for item in fetched:
        snippets.append(
            {
                "text": safe_str(getattr(item, "text", "")).strip(),
                "start": safe_float(getattr(item, "start", 0.0)),
                "duration": safe_float(getattr(item, "duration", 0.0)),
            }
        )
    full_text = "\n".join(item["text"] for item in snippets if item["text"])
    return snippets, full_text, estimate_duration_seconds(snippets)


def normalize_raw_entries(raw_entries: object) -> list[dict[str, Any]]:
    if not isinstance(raw_entries, list):
        return []
    snippets = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        snippets.append(
            {
                "text": safe_str(entry.get("text", "")).strip(),
                "start": safe_float(entry.get("start", 0.0)),
                "duration": safe_float(entry.get("duration", 0.0)),
            }
        )
    return snippets


def normalize_language_codes(values: list[str]) -> list[str]:
    normalized = []
    for value in values or []:
        code = str(value or "").strip().lower()
        if code and code not in normalized:
            normalized.append(code)
    return normalized or ["en"]


def estimate_duration_seconds(snippets: list[dict[str, Any]]) -> float:
    if not snippets:
        return 0.0
    last = snippets[-1]
    return max(0.0, safe_float(last.get("start")) + safe_float(last.get("duration")))


def truncate_middle(value: str, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    if max_chars <= 200:
        return text[:max_chars]
    head = int(max_chars * 0.45)
    tail = int(max_chars * 0.45)
    marker = "\n...[transcript truncated for context budget]...\n"
    return text[:head] + marker + text[-tail:]


def summary_instruction(detail: str) -> str:
    if detail == "brief":
        return "Return a strongly compressed overview in 3-5 sentences."
    if detail == "detailed":
        return "Return a thorough summary covering the full flow, key details, examples, and conclusions."
    return "Return a clear summary in about 2 short paragraphs, with key points when useful."


def safe_str(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def safe_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
