"""Verify Markdown conversion for Telegram."""

from pilot.telegram_format import markdown_to_telegram_markdown_v2


def test_unordered_lists_use_readable_bullets():
    markdown = "- First\n  * **Nested**\n+ Third"

    assert markdown_to_telegram_markdown_v2(markdown) == "• First\n  • *Nested*\n• Third"


def test_tables_render_as_compact_monospace_grids():
    markdown = "| Name | Status | Date |\n| --- | --- | --- |\n| Website | Done | 8 Aug |\n| API | Open | 12 Aug |"

    rendered = markdown_to_telegram_markdown_v2(markdown)

    assert rendered.startswith("```\nName")
    assert "Name     Status  Date" in rendered
    assert "───────  ──────  ──────" in rendered
    assert "Website  Done    8 Aug" in rendered
    assert rendered.endswith("\n```")


def test_long_table_cells_wrap_within_mobile_width():
    markdown = (
        "| Task | Status | Note |\n| --- | --- | --- |\n"
        "| Website | Open | Waiting for detailed customer feedback about navigation |"
    )

    rendered = markdown_to_telegram_markdown_v2(markdown)
    table_lines = rendered.splitlines()[1:-1]

    assert max(map(len, table_lines)) <= 42
    assert "customer" in rendered
    assert "feedback" in rendered


def test_too_many_columns_fall_back_to_cards():
    markdown = (
        "| A | B | C | D | E | F | G | H |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |"
    )

    rendered = markdown_to_telegram_markdown_v2(markdown)

    assert not rendered.startswith("```")
    assert "1\\. 1" in rendered
    assert "\\- H: 8" in rendered
