"""Verify Markdown conversion for Telegram."""

from pilot.telegram_format import markdown_to_telegram_markdown_v2


def test_unordered_lists_use_readable_bullets():
    markdown = "- First\n  * **Nested**\n+ Third"

    assert markdown_to_telegram_markdown_v2(markdown) == "• First\n  • *Nested*\n• Third"
