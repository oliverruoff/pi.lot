"""Verify the labels displayed by Telegram's /sessions command."""

import json

from pilot.session_info import read_session_info


def test_reads_first_user_prompt_and_last_message_time(tmp_path):
    session_file = tmp_path / "session.jsonl"
    entries = [
        {
            "type": "message",
            "timestamp": "2026-07-12T08:00:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Behavior\n\nUser prompt:\nExplain the project"}],
            },
        },
        {
            "type": "message",
            "timestamp": "2026-07-12T09:30:00Z",
            "message": {"role": "assistant", "content": []},
        },
    ]
    session_file.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )

    assert read_session_info(str(session_file)) == ("Explain the project", "12.07. 09:30")


def test_missing_session_uses_empty_defaults(tmp_path):
    assert read_session_info(str(tmp_path / "missing.jsonl")) == ("Untitled", "")
