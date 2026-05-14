---
name: youtube-summarizer
description: Fetches YouTube video transcripts and summarizes them. Use when the user provides a YouTube URL or video ID and asks for a summary, key points, overview, recap, or explanation of the video's content.
compatibility: Self-contained skill. Requires Python 3.10+, internet access, and the Python package in requirements.txt installed before first use if not already available.
---

# YouTube Summarizer

Use this skill when the user asks to summarize, recap, explain, or extract key points from a YouTube video.

## First-time setup

This skill is standalone and has no dependency on the host project. From this skill directory (the directory containing `SKILL.md`), install local requirements if they are not already available:

```bash
python -m pip install -r requirements.txt
```

## Usage

Run the transcript helper script with a YouTube URL or 11-character video ID:

From this skill directory (the directory containing `SKILL.md`):

```bash
python scripts/youtube_summarizer.py "https://www.youtube.com/watch?v=VIDEO_ID" --detail standard --languages en
python scripts/youtube_summarizer.py "VIDEO_ID" --detail brief --languages en de
```

Arguments:

- `video`: YouTube URL or video ID. Supports `youtube.com/watch?v=...`, `youtu.be/...`, `/shorts/...`, `/embed/...`, `/live/...`, and raw video IDs.
- `--detail`: `brief`, `standard`, or `detailed`. Defaults to `standard`.
- `--languages`: Preferred transcript language codes in fallback order. Defaults to `en`.
- `--max-chars`: Maximum transcript characters returned. Defaults depend on detail level.

The script prints JSON to stdout. On success, the JSON includes transcript metadata and `transcript_text`. On failure, it exits non-zero and prints a clear error JSON.

## Summarization instructions

After fetching the transcript:

1. Summarize only from the returned transcript text. Do not invent details.
2. If the transcript was truncated, say the summary is based on the available transcript excerpt.
3. Match the requested detail level:
   - `brief`: 3-5 sentence overview.
   - `standard`: concise summary in about 2 short paragraphs, plus key points when useful.
   - `detailed`: thorough summary covering the full flow, arguments, examples, and conclusions.
4. Mention transcript limitations if relevant, such as missing language metadata, generated captions, or unavailable transcript.

Recommended output format:

```markdown
## Summary
...

## Key points
- ...
- ...

## Notes
- Transcript language: ...
- Video: ...
```
