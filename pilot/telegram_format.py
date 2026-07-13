"""Convert common Markdown into messages accepted by Telegram."""

from __future__ import annotations

import re

MAX_MESSAGE_LEN = 4096

# Telegram MarkdownV2 reserved characters.
_MD2_RESERVED = set(r"_*[]()~`>#+-=|{}.!\\")

# Regex patterns for Markdown parsing.
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)")
_LINK_RE = re.compile(r"!?\[([^\]]+)\]\(([^)]+)\)")
_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.+)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_RULE_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_TABLE_RE = re.compile(r"^\s*\|.+?\|.*$")


def escape_markdown_v2(text: str) -> str:
    return "".join(("\\" + ch) if ch in _MD2_RESERVED else ch for ch in text)


def _escape_code_markdown_v2(text: str) -> str:
    # Telegram requires only backslash and backtick escaping inside code/pre.
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _strip_simple_markdown(text: str) -> str:
    text = _LINK_RE.sub(lambda m: m.group(1), text)
    text = _BOLD_RE.sub(lambda m: m.group(2), text)
    text = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2) or "", text)
    return text


def _inline_markdown_to_markdown_v2(text: str) -> str:
    """Convert common Markdown inline syntax to Telegram MarkdownV2.

    Telegram does not understand normal Markdown. If we escaped the raw text,
    users would see literal markers such as **bold**. Instead, protect the
    MarkdownV2 syntax we intentionally emit and escape everything else.
    """
    protected: dict[str, str] = {}

    def protect(value: str) -> str:
        key = f"\x00{len(protected)}\x00"
        protected[key] = value
        return key

    def code_repl(match: re.Match[str]) -> str:
        return protect(f"`{_escape_code_markdown_v2(match.group(1))}`")

    def link_repl(match: re.Match[str]) -> str:
        # Prefer reliable rendering over clickable links: Telegram MarkdownV2 URLs
        # need very strict escaping, while the visible Markdown markers are the
        # main problem this formatter solves.
        label = _strip_simple_markdown(match.group(1))
        url = match.group(2).strip()
        return f"{label} ({url})"

    def bold_repl(match: re.Match[str]) -> str:
        inner = _strip_simple_markdown(match.group(2))
        return protect(f"*{escape_markdown_v2(inner)}*")

    def italic_repl(match: re.Match[str]) -> str:
        inner = match.group(1) or match.group(2) or ""
        inner = _strip_simple_markdown(inner)
        return protect(f"_{escape_markdown_v2(inner)}_")

    text = _CODE_SPAN_RE.sub(code_repl, text)
    text = _LINK_RE.sub(link_repl, text)
    text = _BOLD_RE.sub(bold_repl, text)
    text = _ITALIC_RE.sub(italic_repl, text)

    text = escape_markdown_v2(text)

    # Protected replacements may contain other protected markers when Markdown is
    # nested, e.g. **`/reload`**. Restore until no markers remain.
    for _ in range(len(protected) + 1):
        changed = False
        for key, value in protected.items():
            if key in text:
                text = text.replace(key, value)
                changed = True
        if not changed:
            break

    return text


def _parse_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_table_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _render_table_as_cards(table_lines: list[str]) -> list[str] | None:
    rows = [_parse_table_row(line) for line in table_lines]
    if len(rows) < 2 or not _is_table_separator(rows[1]):
        return None

    headers = rows[0]
    body_rows = rows[2:]
    if len(headers) < 2 or not body_rows:
        return None

    width = len(headers)
    normalized: list[list[str]] = []
    for row in body_rows:
        if len(row) < 2:
            continue
        normalized.append((row + [""] * width)[:width])

    if not normalized:
        return None

    rendered: list[str] = []

    if width == 2:
        rendered.append(
            f"{_inline_markdown_to_markdown_v2(headers[0])} / {_inline_markdown_to_markdown_v2(headers[1])}"
        )
        rendered.append("")
        for key, value in normalized:
            rendered.append(f"\\- {_inline_markdown_to_markdown_v2(key)}: {_inline_markdown_to_markdown_v2(value)}")
        return rendered

    rendered.append("Table")
    rendered.append("")
    for idx, row in enumerate(normalized, start=1):
        title = row[0] or f"Row {idx}"
        rendered.append(f"{idx}\\. {_inline_markdown_to_markdown_v2(title)}")
        for header, value in zip(headers[1:], row[1:]):
            if value:
                rendered.append(f"\\- {_inline_markdown_to_markdown_v2(header)}: {_inline_markdown_to_markdown_v2(value)}")
        rendered.append("")

    if rendered[-1] == "":
        rendered.pop()

    return rendered


def _flush_table(table_lines: list[str], lines: list[str]) -> None:
    if not table_lines:
        return

    rendered = _render_table_as_cards(table_lines)
    if rendered is not None:
        lines.extend(rendered)
    else:
        lines.append("```")
        for tl in table_lines:
            lines.append(_escape_code_markdown_v2(tl))
        lines.append("```")

    table_lines.clear()


def markdown_to_telegram_markdown_v2(text: str) -> str:
    """Best-effort conversion from common Markdown to Telegram MarkdownV2."""
    lines: list[str] = []
    table_lines: list[str] = []
    in_fence = False

    for raw_line in text.splitlines():
        if _FENCE_RE.match(raw_line):
            _flush_table(table_lines, lines)
            lines.append("```")
            in_fence = not in_fence
            continue

        if in_fence:
            _flush_table(table_lines, lines)
            lines.append(_escape_code_markdown_v2(raw_line))
            continue

        if _TABLE_RE.match(raw_line):
            table_lines.append(raw_line)
            continue

        _flush_table(table_lines, lines)

        if not raw_line:
            lines.append("")
            continue

        if _RULE_RE.match(raw_line):
            lines.append("—")
            continue

        heading = _HEADING_RE.match(raw_line)
        if heading:
            title = _strip_simple_markdown(heading.group(1)).strip()
            lines.append(f"*{escape_markdown_v2(title)}*")
            continue

        bullet = _BULLET_RE.match(raw_line)
        if bullet:
            indent = escape_markdown_v2(bullet.group(1))
            lines.append(f"{indent}• {_inline_markdown_to_markdown_v2(bullet.group(2))}")
            continue

        ordered = _ORDERED_RE.match(raw_line)
        if ordered:
            indent, number, body = ordered.groups()
            lines.append(f"{escape_markdown_v2(indent)}{number}\\. {_inline_markdown_to_markdown_v2(body)}")
            continue

        quote = _QUOTE_RE.match(raw_line)
        if quote:
            lines.append(f"\\> {_inline_markdown_to_markdown_v2(quote.group(1))}")
            continue

        lines.append(_inline_markdown_to_markdown_v2(raw_line))

    _flush_table(table_lines, lines)

    if in_fence:
        lines.append("```")

    return "\n".join(lines)


def chunks(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    if not text:
        return [""]

    out: list[str] = []
    remaining = text

    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        out.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n ")

    out.append(remaining)
    return out


def format_for_telegram(text: str, markdown_v2: bool = True) -> list[str]:
    if markdown_v2:
        # Convert before chunking because escaping/conversion changes size.
        text = markdown_to_telegram_markdown_v2(text)
    return chunks(text)
