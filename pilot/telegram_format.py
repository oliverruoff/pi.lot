from __future__ import annotations

MAX_MESSAGE_LEN = 4096
# Telegram MarkdownV2 reserved characters.
_MD2_RESERVED = set(r"_*[]()~`>#+-=|{}.!\\")


def escape_markdown_v2(text: str) -> str:
    return "".join(("\\" + ch) if ch in _MD2_RESERVED else ch for ch in text)


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
        # Escape before chunking because escaping increases size.
        text = escape_markdown_v2(text)
    return chunks(text)
