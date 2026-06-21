import html
import re


def strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw or "")
    return html.unescape(text).strip()


def truncate(text: str, max_chars: int = 200) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def to_html(text: str) -> str:
    lines = [f"<p>{html.escape(line)}</p>" for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
