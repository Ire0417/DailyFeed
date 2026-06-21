"""
ReportBuilder - aggregates recent summaries into a single Markdown report.
"""
from datetime import datetime, date
from internal.infrastructure.monitoring.logger import get_logger
from internal.pipeline.aggregator.template import ReportTemplate

logger = get_logger("report_builder")


class ReportBuilder:
    def __init__(self, template: ReportTemplate | str | None = None):
        if isinstance(template, ReportTemplate):
            self.template = template
        elif isinstance(template, str):
            self.template = ReportTemplate(template)
        else:
            self.template = ReportTemplate("default")

    async def build(self, summaries_by_source: dict[str, list[dict]] | list) -> dict:
        """
        Build a report from summaries. Two input shapes supported:

        - dict: {source_label: [ {title, url, summary, published_at, author}, ... ], ... }
        - list: [ {source, title, url, summary, published_at, author}, ... ]

        Returns:
            {title, markdown_body, stats}
        """
        today = date.today().isoformat()
        sections: list[str] = []
        total_items = 0
        total_sources = 0

        if isinstance(summaries_by_source, dict):
            for source_label, items in summaries_by_source.items():
                if not items:
                    continue
                total_sources += 1
                total_items += len(items)
                sections.append(self._render_section(source_label, items))
        else:
            # grouped list
            grouped: dict[str, list[dict]] = {}
            for item in summaries_by_source or []:
                key = item.get("source") or "其他"
                grouped.setdefault(key, []).append(item)
            for source_label, items in grouped.items():
                total_sources += 1
                total_items += len(items)
                sections.append(self._render_section(source_label, items))

        title = f"每日摘要 - {today}"
        sections_text = "\n\n".join(sections)
        markdown_body = self.template.render(
            sections=sections_text, total_items=total_items, total_sources=total_sources,
        )

        stats = {
            "total_items": total_items,
            "total_sources": total_sources,
            "generated_at": datetime.utcnow().isoformat(),
        }

        logger.info("report built: %d items, %d sources", total_items, total_sources)
        return {
            "title": title,
            "markdown_body": markdown_body,
            "html_body": _markdown_to_html(markdown_body),
            "stats": stats,
        }

    # ---------- helpers ----------
    def _render_section(self, source_label: str, items: list[dict]) -> str:
        lines = [f"## {source_label}（{len(items)}）"]
        for it in items:
            title = it.get("title") or "(无标题)"
            url = it.get("url") or "#"
            summary = it.get("summary") or ""
            published_at = it.get("published_at")
            if hasattr(published_at, "isoformat"):
                published_at = published_at.isoformat()[:10]

            item_block = [
                f"- [{title}]({url}){' ' + str(published_at) if published_at else ''}",
            ]
            if summary:
                # Indent summary lines under bullet.
                for s in str(summary).splitlines():
                    item_block.append(f"    > {s}")
            lines.append("\n".join(item_block))
        return "\n\n".join(lines)


def _markdown_to_html(md: str) -> str:
    """
    Very small Markdown -> HTML renderer suitable for email reports.
    Supports headers, bullets, bold, links, and blockquotes.
    """
    import re

    # Escape HTML
    html = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Bold: **text**
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)

    # Inline links: [label](url)
    html = re.sub(
        r"\[([^\]]+)\]\(([^\)]+)\)",
        r'<a href="\2">\1</a>',
        html,
    )

    # Headers
    lines = html.splitlines()
    out: list[str] = []
    in_list = False
    in_quote = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            in_list = _flush_list(out, in_list)
            in_quote = _flush_quote(out, in_quote)
            out.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            in_list = _flush_list(out, in_list)
            in_quote = _flush_quote(out, in_quote)
            out.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            in_list = _flush_list(out, in_list)
            in_quote = _flush_quote(out, in_quote)
            out.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            in_quote = _flush_quote(out, in_quote)
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{stripped[2:]}</li>")
        elif stripped.startswith("> "):
            in_list = _flush_list(out, in_list)
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            out.append(stripped[2:])
        elif stripped == "":
            in_list = _flush_list(out, in_list)
            in_quote = _flush_quote(out, in_quote)
            out.append("<br/>")
        else:
            in_list = _flush_list(out, in_list)
            in_quote = _flush_quote(out, in_quote)
            out.append(f"<p>{stripped}</p>")

    _flush_list(out, in_list)
    _flush_quote(out, in_quote)

    return "<html><body>" + "\n".join(out) + "</body></html>"


def _flush_list(out: list[str], in_list: bool) -> bool:
    if in_list:
        out.append("</ul>")
    return False


def _flush_quote(out: list[str], in_quote: bool) -> bool:
    if in_quote:
        out.append("</blockquote>")
    return False
